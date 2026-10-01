"""Command-line entry point for safe, YAML-defined Biz Intel jobs."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from biz_intel.jobs import JobRunner, load_job


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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run a command and return a conventional process exit status."""

    args = build_parser().parse_args(argv)
    # Source registration is centralized so CLI behavior has the same policy
    # gates as embedded use of JobRunner.
    from main import register_sources

    register_sources()
    job = load_job(args.job)
    runner = JobRunner(progress_reporter=None if args.quiet else print)
    if args.command == "preflight":
        print(json.dumps(runner.preflight(job).to_dict(), indent=2, sort_keys=True))
        return 0

    result = runner.run(
        job,
        resume_from=args.checkpoint if args.command == "resume" else None,
    )
    print(result.summary())
    return 0


if __name__ == "__main__":  # pragma: no cover - package entry point uses main
    raise SystemExit(main())
