"""Focused tests for the public command-line job workflow."""

from __future__ import annotations

from unittest.mock import Mock, patch
import unittest

from biz_intel import cli


class CliTests(unittest.TestCase):
    @patch("biz_intel.cli.JobRunner")
    @patch("biz_intel.cli.load_job", return_value=object())
    @patch("main.register_sources")
    def test_preflight_prints_json_without_running_a_job(
        self, register_sources: Mock, load_job: Mock, runner_class: Mock
    ) -> None:
        runner_class.return_value.preflight.return_value.to_dict.return_value = {"task_count": 1}

        with patch("builtins.print") as print_mock:
            exit_code = cli.main(["preflight", "jobs/example.yaml", "--quiet"])

        self.assertEqual(exit_code, 0)
        register_sources.assert_called_once_with()
        runner_class.assert_called_once_with(progress_reporter=None)
        runner_class.return_value.run.assert_not_called()
        self.assertIn('"task_count": 1', print_mock.call_args.args[0])

    @patch("biz_intel.cli.JobRunner")
    @patch("biz_intel.cli.load_job", return_value=object())
    @patch("main.register_sources")
    def test_resume_passes_checkpoint_to_runner(
        self, register_sources: Mock, load_job: Mock, runner_class: Mock
    ) -> None:
        runner_class.return_value.run.return_value.summary.return_value = "done"

        exit_code = cli.main(["resume", "jobs/example.yaml", "runs/run.checkpoint.json", "--quiet"])

        self.assertEqual(exit_code, 0)
        runner_class.return_value.run.assert_called_once_with(
            load_job.return_value,
            resume_from="runs/run.checkpoint.json",
        )


if __name__ == "__main__":
    unittest.main()
