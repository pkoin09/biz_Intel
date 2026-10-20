"""Command-line entry point for safe, YAML-defined Biz Intel jobs."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from biz_intel.config import config
from biz_intel.jobs import JobRunner, load_job
from biz_intel.models import Business
from biz_intel.research import (
    MediCalDentalEnrollmentPlugin,
    LongevityEvidencePlugin,
    OperationalStatusEvidencePlugin,
    OwnershipEvidencePlugin,
    PublicEmailPlugin,
    PublicSocialPlugin,
    ResearchRunner,
    ResearchSession,
    compose_research_session,
    export_research_session,
    import_research_session,
    latest_refinement_records,
    latest_refinement_steps,
    list_research_sessions,
    research_session_summary,
    review_overture_snapshot,
    select_latest_research_session,
)
from biz_intel.services.enrichment import FirstPartyWebsiteCrawler, SocialEnricher
from biz_intel.sources.overture import prepare_overture_snapshot


_VIEW_FIELDS = {
    "name",
    "address",
    "city",
    "state",
    "postal_code",
    "phone",
    "website",
    "email",
    "linkedin",
    "instagram",
    "facebook",
    "twitter",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="biz-intel",
        description="Run approved Biz Intel YAML jobs.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    for command, help_text in (
        ("preflight", "Show no-I/O execution and known-spend ceilings."),
        ("run", "Execute a job and write its delivery artifacts."),
    ):
        subparser = subcommands.add_parser(command, help=help_text)
        subparser.add_argument("job", help="Path to a versioned YAML job.")
        subparser.add_argument(
            "--quiet",
            action="store_true",
            help="Suppress stage-progress messages.",
        )
    resume = subcommands.add_parser("resume", help="Continue from a sanitized checkpoint.")
    resume.add_argument("job", help="Path to the exact YAML job used originally.")
    resume.add_argument("checkpoint", help="Path to the run checkpoint JSON.")
    resume.add_argument("--quiet", action="store_true", help="Suppress stage-progress messages.")
    research = subcommands.add_parser(
        "research",
        help="Run an existing search job and preserve its results as a research session.",
    )
    research.add_argument("job", help="Path to a versioned YAML search job.")
    research.add_argument("request", help="The plain-language research request.")
    research.add_argument(
        "--session",
        help="Optional research-session JSON destination.",
    )
    research.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress stage-progress messages.",
    )
    refine = subcommands.add_parser(
        "refine",
        help="Apply a supported plain-language refinement to a research session.",
    )
    refine.add_argument(
        "--latest",
        nargs="?",
        const=1,
        type=int,
        metavar="N",
        help="Use the newest session, or the Nth newest session.",
    )
    refine.add_argument(
        "arguments",
        nargs="+",
        help="SESSION INSTRUCTION, or just INSTRUCTION when using --latest.",
    )
    subcommands.add_parser(
        "sessions",
        help="List saved research sessions, newest first.",
    )
    compose = subcommands.add_parser(
        "compose",
        help="Attach website candidates from a supplemental CSV or JSON result set.",
    )
    compose.add_argument(
        "arguments",
        nargs="+",
        help="SESSION SOURCE_FILE..., or SOURCE_FILE... when using --latest.",
    )
    compose.add_argument(
        "--latest",
        nargs="?",
        const=1,
        type=int,
        metavar="N",
        help="Use the newest session, or the Nth newest session.",
    )
    compose.add_argument(
        "--source",
        help="Source name for supplemental rows that do not include one.",
    )
    view = subcommands.add_parser(
        "view",
        help="Show names and phone numbers without changing a research session.",
    )
    view.add_argument("session", nargs="?", help="Session name or JSON path.")
    view.add_argument(
        "--latest",
        nargs="?",
        const=1,
        type=int,
        metavar="N",
        help="Use the newest session, or the Nth newest session.",
    )
    view.add_argument(
        "--all",
        action="store_true",
        help="Preview all session records instead of latest-refinement matches.",
    )
    view.add_argument(
        "--audit",
        nargs="?",
        const=0,
        type=int,
        metavar="N",
        help="Show the latest instruction audit group, or the Nth latest step.",
    )
    view.add_argument(
        "--summary",
        action="store_true",
        help="Show session coverage and latest-match counts instead of rows.",
    )
    view.add_argument(
        "-n",
        "--limit",
        type=int,
        default=20,
        help="Maximum rows to show (default: 20); -10 is shorthand for -n 10.",
    )
    view.add_argument(
        "--fields",
        default="name,phone",
        help="Comma-separated safe fields to show (default: name,phone).",
    )
    view.add_argument(
        "--with",
        dest="with_field",
        choices=sorted(_VIEW_FIELDS - {"name"}),
        help="Show session records where this field is populated.",
    )
    research_export = subcommands.add_parser(
        "research-export",
        help="Export a clean CSV or JSON view of a research session.",
    )
    research_export.add_argument(
        "arguments",
        nargs="+",
        help="SESSION DESTINATION, or DESTINATION when using --latest.",
    )
    research_export.add_argument(
        "--latest",
        nargs="?",
        const=1,
        type=int,
        metavar="N",
        help="Use the newest session, or the Nth newest session.",
    )
    research_export.add_argument(
        "--matches",
        action="store_true",
        help="Export only records satisfying every criterion in the latest instruction.",
    )
    research_import = subcommands.add_parser(
        "research-import",
        help="Continue research from an existing CSV or JSON result set.",
    )
    research_import.add_argument("source", help="Existing result file ending in .csv or .json.")
    research_import.add_argument("request", help="The plain-language research request.")
    research_import.add_argument(
        "--session",
        help="Optional research-session JSON destination.",
    )
    overture_snapshot = subcommands.add_parser(
        "overture-snapshot",
        help="Prepare a reviewed dental candidate snapshot from local Overture Parquet.",
    )
    overture_snapshot.add_argument("source", help="Explicit local Parquet path or glob.")
    overture_snapshot.add_argument("destination", help="New candidate .parquet path.")
    overture_snapshot.add_argument("--release", required=True)
    overture_snapshot.add_argument("--retrieved-at", required=True)
    overture_snapshot.add_argument("--source-reference", required=True)
    overture_snapshot.add_argument(
        "--bbox",
        nargs=4,
        type=float,
        required=True,
        metavar=("WEST", "SOUTH", "EAST", "NORTH"),
    )
    overture_snapshot.add_argument("--geography", required=True)
    overture_snapshot.add_argument("--license", required=True)
    overture_snapshot.add_argument("--attribution", required=True)
    overture_snapshot.add_argument(
        "--locality",
        action="append",
        default=[],
        help="Optional address locality to keep; repeat for several cities.",
    )
    overture_snapshot.add_argument("--manifest", help="Optional manifest destination.")
    overture_review = subcommands.add_parser(
        "overture-review",
        help="Preview matches from a verified Overture snapshot without changing a session.",
    )
    overture_review.add_argument("snapshot", help="Prepared Overture candidate Parquet.")
    overture_review.add_argument("session", nargs="?", help="Session name or JSON path.")
    overture_review.add_argument(
        "--latest",
        nargs="?",
        const=1,
        type=int,
        metavar="N",
        help="Use the newest session, or the Nth newest session.",
    )
    overture_review.add_argument(
        "-n", "--limit", type=int, default=20, help="Maximum match rows to preview."
    )
    overture_review.add_argument(
        "--offset", type=int, default=0, help="Skip this many rows in the selected queue."
    )
    overture_review.add_argument(
        "--decision",
        choices=("matched", "candidate", "ambiguous"),
        help="Show only one decision queue while retaining counts for all decisions.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run a command and return a conventional process exit status."""

    command_line = list(argv) if argv is not None else sys.argv[1:]
    args = build_parser().parse_args(_normalize_cli(command_line))
    research_directory = config.RUNS_PATH / "research"

    if args.command == "overture-snapshot":
        prepared = prepare_overture_snapshot(
            args.source,
            args.destination,
            release=args.release,
            retrieved_at=args.retrieved_at,
            source_reference=args.source_reference,
            bbox=args.bbox,
            geography_label=args.geography,
            license=args.license,
            attribution=args.attribution,
            manifest_path=args.manifest,
            localities=args.locality,
        )
        print(
            f"Overture candidate snapshot: {prepared.row_count} records -> "
            f"{_display_path(prepared.snapshot_path)} "
            f"(manifest: {_display_path(prepared.manifest_path)})"
        )
        return 0

    if args.command == "overture-review":
        if args.session and args.latest is not None:
            raise ValueError("overture-review accepts either SESSION or --latest, not both.")
        if args.session:
            session_path = _resolve_session_path(args.session, research_directory)
            session = ResearchSession.load(session_path)
        else:
            selected = select_latest_research_session(
                research_directory,
                args.latest if args.latest is not None else 1,
            )
            session = selected.session
        print(
            json.dumps(
                review_overture_snapshot(
                    session,
                    args.snapshot,
                    limit=args.limit,
                    offset=args.offset,
                    decision=args.decision,
                ),
                indent=2,
            )
        )
        return 0

    if args.command == "sessions":
        sessions = list_research_sessions(research_directory)
        if not sessions:
            print(f"No saved research sessions in {research_directory}")
            return 0
        for position, saved in enumerate(sessions, start=1):
            session = saved.session
            print(
                f"{position:>2}  {saved.path.stem}  "
                f"{len(session.businesses)} records  "
                f"{len(session.refinements)} refinements  "
                f"{len(session.compositions)} compositions  "
                f"{session.request}"
            )
        return 0

    if args.command == "view":
        if args.session and args.latest is not None:
            raise ValueError("view accepts either SESSION or --latest, not both.")
        if args.session:
            session_path = _resolve_session_path(args.session, research_directory)
            session = ResearchSession.load(session_path)
        else:
            selected = select_latest_research_session(
                research_directory,
                args.latest if args.latest is not None else 1,
            )
            session_path = selected.path
            session = selected.session
        if args.limit < 1:
            raise ValueError("view limit must be 1 or greater.")
        if args.audit is not None and args.summary:
            raise ValueError("view accepts either --audit or --summary, not both.")
        if args.audit is not None:
            if args.audit < 0:
                raise ValueError("--audit must be 1 or greater.")
            if args.audit == 0:
                if not session.refinements:
                    payload = None
                else:
                    instruction = session.refinements[-1].instruction
                    steps = latest_refinement_steps(session)
                    payload = {
                        "instruction": instruction,
                        "plugins": [
                            {
                                "plugin": step.plugin,
                                "note": step.note,
                                "details": list(step.details),
                            }
                            for step in steps
                        ],
                    }
                print(json.dumps(payload, indent=2))
                return 0
            if args.audit > len(session.refinements):
                step = None
            else:
                step = session.refinements[-args.audit]
            print(
                json.dumps(
                    None
                    if step is None
                    else {
                        "instruction": step.instruction,
                        "plugin": step.plugin,
                        "note": step.note,
                        "details": list(step.details),
                    },
                    indent=2,
                )
            )
            return 0
        if args.summary:
            print(json.dumps(research_session_summary(session), indent=2))
            return 0
        fields = [field.strip() for field in args.fields.split(",") if field.strip()]
        invalid_fields = sorted(set(fields) - _VIEW_FIELDS)
        if not fields or invalid_fields:
            allowed = ", ".join(sorted(_VIEW_FIELDS))
            invalid = ", ".join(invalid_fields) or "empty selection"
            raise ValueError(f"Unsupported view fields ({invalid}). Choose from: {allowed}.")
        if args.with_field:
            records = [
                business
                for business in session.businesses
                if getattr(business, args.with_field)
            ]
        else:
            records = session.businesses if args.all else latest_refinement_records(session)
        visible_records = records[: args.limit]
        print(
            json.dumps(
                [
                    {field: getattr(business, field) or None for field in fields}
                    for business in visible_records
                ],
                indent=2,
            )
        )
        return 0

    if args.command == "compose":
        if args.latest is None:
            if len(args.arguments) < 2:
                raise ValueError("compose requires SESSION and at least one SOURCE_FILE.")
            session_path = _resolve_session_path(args.arguments[0], research_directory)
            source_files = args.arguments[1:]
        else:
            if not args.arguments:
                raise ValueError("compose --latest requires at least one SOURCE_FILE.")
            selected = select_latest_research_session(research_directory, args.latest)
            session_path = selected.path
            source_files = args.arguments
        session = ResearchSession.load(session_path)
        steps = [
            compose_research_session(session, source_file, source=args.source)
            for source_file in source_files
        ]
        session.save(session_path)
        print(
            f"Composition: {sum(step.matched_count for step in steps)} matched, "
            f"{sum(step.ambiguous_count + step.candidate_count for step in steps)} "
            f"for review, {sum(step.website_count for step in steps)} websites attached "
            f"from {len(steps)} file(s), "
            f"{sum(step.contact_count for step in steps)} reviewed contacts attached "
            f"-> {_display_path(session_path)}"
        )
        return 0

    if args.command == "research-import":
        session = import_research_session(args.source, args.request)
        destination = (
            Path(args.session)
            if args.session
            else config.RUNS_PATH / "research" / f"{Path(args.source).stem}-{session.session_id}.json"
        )
        session.save(destination)
        print(
            f"Research session: {len(session.businesses)} records -> "
            f"{_display_path(destination)}"
        )
        return 0

    if args.command == "research-export":
        if args.latest is None:
            if len(args.arguments) != 2:
                raise ValueError("research-export requires SESSION and DESTINATION.")
            session_path = _resolve_session_path(args.arguments[0], research_directory)
            destination_path = args.arguments[1]
        else:
            if len(args.arguments) != 1:
                raise ValueError("research-export --latest requires one DESTINATION.")
            selected = select_latest_research_session(research_directory, args.latest)
            session_path = selected.path
            destination_path = args.arguments[0]
        session = ResearchSession.load(session_path)
        businesses = latest_refinement_records(session) if args.matches else session.businesses
        destination = export_research_session(
            session,
            destination_path,
            businesses=businesses,
        )
        print(
            f"Research export: {len(businesses)} records -> "
            f"{_display_path(destination)}"
        )
        return 0

    if args.command == "refine":
        if args.latest is None:
            if len(args.arguments) != 2:
                raise ValueError("refine requires SESSION and INSTRUCTION.")
            session_path = _resolve_session_path(args.arguments[0], research_directory)
            instruction_text = args.arguments[1]
        else:
            if len(args.arguments) != 1:
                raise ValueError("refine --latest requires one INSTRUCTION.")
            selected = select_latest_research_session(research_directory, args.latest)
            session_path = selected.path
            instruction_text = args.arguments[0]

        session = ResearchSession.load(session_path)
        print(
            f"Selected session: {session.request} "
            f"({len(session.businesses)} records) -> {_display_path(session_path)}"
        )
        instruction = instruction_text.casefold()
        plugins = []
        if "medi-cal" in instruction or "medi cal" in instruction:
            plugins.append(MediCalDentalEnrollmentPlugin())
        ownership_requested = any(
            phrase in instruction
            for phrase in (
                "family owned",
                "family-owned",
                "independent",
                "locally owned",
                "locally-owned",
                "corporate",
                "corporation",
            )
        )
        longevity_requested = any(
            phrase in instruction
            for phrase in ("years", "been open", "founded", "established", "long-running")
        )
        social_requested = any(
            phrase in instruction
            for phrase in ("linkedin", "instagram", "facebook", "twitter", "social")
        )
        email_requested = "email" in instruction or "contact address" in instruction
        closure_requested = any(
            phrase in instruction for phrase in ("closed", "retired", "inactive")
        )
        crawler = (
            FirstPartyWebsiteCrawler()
            if any(
                (
                    ownership_requested,
                    longevity_requested,
                    social_requested,
                    email_requested,
                    closure_requested,
                )
            )
            else None
        )
        if ownership_requested:
            plugins.append(OwnershipEvidencePlugin(crawler))
        if longevity_requested:
            plugins.append(LongevityEvidencePlugin(crawler))
        if closure_requested:
            plugins.append(OperationalStatusEvidencePlugin(crawler))
        enricher = SocialEnricher(crawler=crawler) if crawler is not None else None
        if social_requested:
            plugins.append(PublicSocialPlugin(enricher))
        if email_requested:
            plugins.append(PublicEmailPlugin(enricher))
        if not plugins:
            raise ValueError(
                "This skeleton currently supports Medi-Cal Dental and "
                "independent/family-owned, business-longevity, public-email, "
                "explicit closure, or social refinements."
            )
        runner = ResearchRunner(plugins)
        first_new_step = len(session.refinements)
        for plugin in plugins:
            runner.refine(
                session,
                instruction_text,
                plugin=plugin.name,
            )
        session.save(session_path)
        for step in session.refinements[first_new_step:]:
            print(f"[{step.plugin}] {step.note}")
        print(
            f"Research session updated: {len(session.businesses)} records, "
            f"{len(plugins)} plugin(s) applied -> {_display_path(session_path)}"
        )
        return 0

    # Source registration is centralized so CLI behavior has the same policy
    # gates as embedded use of JobRunner.
    from main import register_sources

    register_sources()
    job = load_job(args.job)
    runner = JobRunner(progress_reporter=None if args.quiet else print)
    if args.command == "preflight":
        print(json.dumps(runner.preflight(job).to_dict(), indent=2, sort_keys=True))
        return 0

    if args.command == "research":
        businesses: list[Business] = []
        result = runner.run(job, record_consumer=businesses.extend)
        session = ResearchSession(args.request, businesses)
        destination = (
            Path(args.session)
            if args.session
            else config.RUNS_PATH / "research" / f"{result.run_id}.json"
        )
        session.save(destination)
        print(result.summary())
        print(
            f"Research session: {len(businesses)} records -> "
            f"{_display_path(destination)}"
        )
        return 0

    result = runner.run(
        job,
        resume_from=args.checkpoint if args.command == "resume" else None,
    )
    print(result.summary())
    return 0


def _display_path(value: str | Path) -> str:
    """Show useful paths without exposing an absolute local home directory."""

    path = Path(value)
    if not path.is_absolute():
        return str(path)
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return path.name


def _normalize_cli(argv: list[str]) -> list[str]:
    """Support compact terminal shorthand before handing off to argparse."""

    normalized = list(argv)
    if normalized and normalized[0] == "view":
        for position, value in enumerate(normalized[1:], start=1):
            if (
                value.startswith("-")
                and not value.startswith("--")
                and value[1:].isdigit()
                and normalized[position - 1] != "--latest"
            ):
                normalized[position : position + 1] = ["--limit", value[1:]]
                break

    if "--latest" not in normalized:
        return normalized
    position = normalized.index("--latest")
    next_value = normalized[position + 1] if position + 1 < len(normalized) else None
    if next_value is None:
        return [*normalized[:position], "--latest=1", *normalized[position + 1 :]]
    try:
        int(next_value)
    except ValueError:
        return [*normalized[:position], "--latest=1", *normalized[position + 1 :]]
    return normalized


def _resolve_session_path(value: str, directory: Path) -> Path:
    """Accept an explicit path or a session name copied from ``sessions``."""

    supplied = Path(value)
    if supplied.exists() or supplied.parent != Path("."):
        return supplied
    filename = supplied.name if supplied.suffix == ".json" else f"{supplied.name}.json"
    return directory / filename


if __name__ == "__main__":  # pragma: no cover - package entry point uses main
    raise SystemExit(main())
