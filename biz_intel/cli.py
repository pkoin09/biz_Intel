"""Command-line entry point for safe, YAML-defined Biz Intel jobs."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from biz_intel.config import config
from biz_intel.jobs import JobRunner, load_job
from biz_intel.models import Business
from biz_intel.research import (
    MediCalDentalEnrollmentPlugin,
    OwnershipEvidencePlugin,
    PublicEmailPlugin,
    PublicSocialPlugin,
    ResearchRunner,
    ResearchSession,
    export_research_session,
    import_research_session,
)


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
    refine.add_argument("session", help="Path to a research-session JSON file.")
    refine.add_argument("instruction", help="The next plain-language refinement.")
    research_export = subcommands.add_parser(
        "research-export",
        help="Export a clean CSV or JSON view of a research session.",
    )
    research_export.add_argument("session", help="Path to a research-session JSON file.")
    research_export.add_argument("destination", help="Destination ending in .csv or .json.")
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run a command and return a conventional process exit status."""

    args = build_parser().parse_args(argv)
    if args.command == "research-import":
        session = import_research_session(args.source, args.request)
        destination = (
            Path(args.session)
            if args.session
            else config.RUNS_PATH / "research" / f"{Path(args.source).stem}-{session.session_id}.json"
        )
        session.save(destination)
        print(f"Research session: {len(session.businesses)} records -> {destination}")
        return 0

    if args.command == "research-export":
        session = ResearchSession.load(args.session)
        destination = export_research_session(session, args.destination)
        print(f"Research export: {len(session.businesses)} records -> {destination}")
        return 0

    if args.command == "refine":
        session = ResearchSession.load(args.session)
        instruction = args.instruction.casefold()
        if "medi-cal" in instruction or "medi cal" in instruction:
            plugin = MediCalDentalEnrollmentPlugin()
        elif any(
            phrase in instruction
            for phrase in ("family owned", "family-owned", "independent", "corporate")
        ):
            plugin = OwnershipEvidencePlugin()
        elif any(
            phrase in instruction
            for phrase in ("linkedin", "instagram", "facebook", "twitter", "social")
        ):
            plugin = PublicSocialPlugin()
        elif "email" in instruction or "contact address" in instruction:
            plugin = PublicEmailPlugin()
        else:
            raise ValueError(
                "This skeleton currently supports Medi-Cal Dental and "
                "independent/family-owned, public-email, or social refinements."
            )
        runner = ResearchRunner([plugin])
        runner.refine(
            session,
            args.instruction,
            plugin=plugin.name,
        )
        session.save(args.session)
        step = session.refinements[-1]
        print(step.note)
        print(f"Research session updated: {step.after_count} records -> {args.session}")
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
        print(f"Research session: {len(businesses)} records -> {destination}")
        return 0

    result = runner.run(
        job,
        resume_from=args.checkpoint if args.command == "resume" else None,
    )
    print(result.summary())
    return 0


if __name__ == "__main__":  # pragma: no cover - package entry point uses main
    raise SystemExit(main())
