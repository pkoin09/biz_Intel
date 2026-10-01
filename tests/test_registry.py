"""Tests for the source plugin registry."""

from __future__ import annotations

from dataclasses import replace
import unittest

from biz_intel.core.registry import SourceRegistry
from biz_intel.core.source_kind import SourceKind
from biz_intel.core.source_name import SourceName
from biz_intel.core.source_policy import CLIENT_INPUT_POLICY
from biz_intel.core.source_policy import EXPERIMENTAL_OR_DISALLOWED_POLICY
from biz_intel.core.source_policy import SourcePolicyError
from biz_intel.core.source_task import SourceTask


class _FakeExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[type, SourceTask]] = []

    def run(self, source_class, task):
        self.calls.append((source_class, task))
        return iter(["fake-result"])


class _FakeSource:
    pass


class SourceRegistryTests(unittest.TestCase):
    """Protect the registry's public contract."""

    def test_register_and_get_return_the_class(self) -> None:
        registry = SourceRegistry()
        registry.register(
            "demo", _FakeSource, kind=SourceKind.FILE, policy=CLIENT_INPUT_POLICY
        )

        self.assertIs(registry.get("demo"), _FakeSource)
        self.assertEqual(registry.get_kind("demo"), SourceKind.FILE)
        self.assertIs(registry.get_policy("demo"), CLIENT_INPUT_POLICY)

    def test_register_rejects_duplicate_names(self) -> None:
        registry = SourceRegistry()
        registry.register(
            "demo", _FakeSource, kind=SourceKind.FILE, policy=CLIENT_INPUT_POLICY
        )

        with self.assertRaises(ValueError):
            registry.register(
                "demo", _FakeSource, kind=SourceKind.FILE, policy=CLIENT_INPUT_POLICY
            )

    def test_run_dispatches_to_the_executor_for_the_registered_kind(self) -> None:
        file_executor = _FakeExecutor()
        registry = SourceRegistry(executors={SourceKind.FILE: file_executor})
        registry.register(
            "demo", _FakeSource, kind=SourceKind.FILE, policy=CLIENT_INPUT_POLICY
        )

        task = SourceTask(source=SourceName.YELLOWPAGES)
        results = list(registry.run("demo", task))

        self.assertEqual(results, ["fake-result"])
        self.assertEqual(file_executor.calls, [(_FakeSource, task)])

    def test_rejects_experimental_source_for_delivery(self) -> None:
        registry = SourceRegistry()
        registry.register(
            "demo",
            _FakeSource,
            kind=SourceKind.FILE,
            policy=EXPERIMENTAL_OR_DISALLOWED_POLICY,
        )

        with self.assertRaisesRegex(
            SourcePolicyError,
            r"demo \(experimental_or_disallowed; delivery disabled\)",
        ):
            registry.require_delivery_approval(("demo",))

    def test_live_smoke_requires_separate_source_approval(self) -> None:
        registry = SourceRegistry()
        registry.register(
            "demo", _FakeSource, kind=SourceKind.FILE, policy=CLIENT_INPUT_POLICY
        )

        with self.assertRaisesRegex(
            SourcePolicyError,
            r"demo \(client_input; live smoke disabled\)",
        ):
            registry.require_live_smoke_approval(("demo",))

        approved_policy = replace(
            CLIENT_INPUT_POLICY,
            live_smoke_allowed=True,
            cost_model="zero-spend",
        )
        registry = SourceRegistry()
        registry.register(
            "approved", _FakeSource, kind=SourceKind.FILE, policy=approved_policy
        )
        registry.require_live_smoke_approval(("approved",))

    def test_live_smoke_rejects_an_approved_but_paid_source(self) -> None:
        registry = SourceRegistry()
        registry.register(
            "paid",
            _FakeSource,
            kind=SourceKind.FILE,
            policy=replace(
                CLIENT_INPUT_POLICY,
                live_smoke_allowed=True,
                cost_model="per-request",
            ),
        )

        with self.assertRaisesRegex(SourcePolicyError, "not zero-spend"):
            registry.require_live_smoke_approval(("paid",))


if __name__ == "__main__":
    unittest.main()
