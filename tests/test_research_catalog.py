"""Tests for terminal-style saved session discovery."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from biz_intel.models import Business
from biz_intel.research import (
    ResearchSession,
    RefinementStep,
    latest_refinement_records,
    latest_refinement_steps,
    list_research_sessions,
    research_session_summary,
    select_latest_research_session,
)


class ResearchCatalogTests(unittest.TestCase):
    def test_lists_valid_sessions_newest_first_and_skips_other_json(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            older = ResearchSession("Older", [Business(name="One")]).save(root / "older.json")
            newer = ResearchSession("Newer", [Business(name="Two")]).save(root / "newer.json")
            (root / "checkpoint.json").write_text('{"not": "a session"}')
            os.utime(older, (100, 100))
            os.utime(newer, (200, 200))

            sessions = list_research_sessions(root)

        self.assertEqual([item.session.request for item in sessions], ["Newer", "Older"])

    def test_selects_a_one_based_latest_position(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = []
            for position in range(1, 4):
                path = ResearchSession(
                    f"Session {position}", [Business(name=str(position))]
                ).save(root / f"session-{position}.json")
                os.utime(path, (position * 100, position * 100))
                paths.append(path)

            selected = select_latest_research_session(root, 3)

        self.assertEqual(selected.session.request, "Session 1")

    def test_rejects_invalid_latest_positions(self) -> None:
        with TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "1 or greater"):
                select_latest_research_session(directory, 0)
            with self.assertRaisesRegex(ValueError, "only 0"):
                select_latest_research_session(directory, 1)

    def test_latest_refinement_records_returns_medi_cal_matches(self) -> None:
        from datetime import datetime, timezone
        from biz_intel.models import Claim

        matched = Business(
            name="Matched",
            claims=(
                Claim(
                    key="program.medi_cal_dental_ffs_enrolled",
                    value=True,
                    source="official",
                    source_record_id="1234567890",
                    evidence_url="https://example.test/dataset",
                    observed_at=datetime.now(timezone.utc),
                ),
            ),
        )
        session = ResearchSession("Dentists", [matched, Business(name="Unknown")])
        session.refinements.append(
            RefinementStep(
                instruction="Medi-Cal",
                plugin="medi-cal-dental-enrollment",
                before_count=2,
                after_count=2,
                applied_at=datetime.now(timezone.utc),
            )
        )

        self.assertEqual(latest_refinement_records(session), [matched])

    def test_latest_refinement_records_intersects_compound_instruction(self) -> None:
        from datetime import datetime, timezone
        from biz_intel.models import Claim

        observed_at = datetime.now(timezone.utc)

        def claim(key: str, value: object) -> Claim:
            return Claim(
                key=key,
                value=value,
                source="evidence",
                source_record_id=f"{key}:{value}",
                evidence_url="https://example.test/evidence",
                observed_at=observed_at,
            )

        complete = Business(
            name="Complete",
            claims=(
                claim("program.medi_cal_dental_ffs_enrolled", True),
                claim("ownership.independence_assessment", "likely_independent"),
                claim("business.longevity.minimum_years", 18),
            ),
        )
        too_new = Business(
            name="Too New",
            claims=(
                claim("program.medi_cal_dental_ffs_enrolled", True),
                claim("ownership.independence_assessment", "likely_independent"),
                claim("business.longevity.minimum_years", 8),
            ),
        )
        corporate = Business(
            name="Corporate",
            claims=(
                claim("program.medi_cal_dental_ffs_enrolled", True),
                claim("ownership.independence_assessment", "likely_corporate"),
                claim("business.longevity.minimum_years", 20),
            ),
        )
        instruction = "Which accept Medi-Cal, are family-owned, and open 10+ years?"
        session = ResearchSession("Dentists", [complete, too_new, corporate])
        for plugin in (
            "medi-cal-dental-enrollment",
            "ownership-evidence",
            "longevity-evidence",
        ):
            session.refinements.append(
                RefinementStep(
                    instruction=instruction,
                    plugin=plugin,
                    before_count=3,
                    after_count=3,
                    applied_at=observed_at,
                )
            )

        self.assertEqual(latest_refinement_records(session), [complete])

        session.refinements[-3:] = [
            RefinementStep(
                instruction="Which are not a corporation?",
                plugin="ownership-evidence",
                before_count=3,
                after_count=3,
                applied_at=observed_at,
            )
        ]
        self.assertEqual(latest_refinement_records(session), [complete, too_new])

        summary = research_session_summary(session)
        self.assertEqual(summary["total_records"], 3)
        self.assertEqual(summary["latest_matches"], 2)
        self.assertEqual(summary["medi_cal_dental_enrolled"], 3)
        self.assertEqual(summary["likely_independent"], 2)
        self.assertEqual(summary["likely_corporate"], 1)
        self.assertEqual(summary["with_longevity_evidence"], 3)
        self.assertEqual(summary["explicitly_closed"], 0)

        session.refinements.extend(session.refinements[-1:])
        self.assertEqual(len(latest_refinement_steps(session)), 1)


if __name__ == "__main__":
    unittest.main()
