"""v1.5 prep: canal de progreso (TD-9) y máquina de estados de migración (TD-4)."""

from __future__ import annotations

import threading
import time
import unittest

from hypergery_ubuntu.v1.errors import HyperGeryError
from hypergery_ubuntu.v1.migration_engine import (
    MigrationCancelled,
    MigrationEngine,
    MigrationPhase,
)
from hypergery_ubuntu.v1.progress import ProgressChannel


class ProgressChannelTests(unittest.TestCase):
    def test_lifecycle_and_versioning(self):
        channel = ProgressChannel()
        op = channel.start("backup", message="empezando")
        state = channel.get(op)
        self.assertEqual(state["status"], "running")
        self.assertEqual(state["version"], 0)
        state = channel.update(op, phase="copy", percent=40, message="copiando", metrics={"mb": 100})
        self.assertEqual(state["phase"], "copy")
        self.assertEqual(state["percent"], 40.0)
        self.assertEqual(state["metrics"], {"mb": 100})
        self.assertEqual(state["version"], 1)
        state = channel.update(op, metrics={"eta": 5})
        self.assertEqual(state["metrics"], {"mb": 100, "eta": 5}, "las métricas se acumulan")
        state = channel.complete(op, "listo")
        self.assertEqual(state["status"], "done")
        self.assertEqual(state["percent"], 100.0)

    def test_percent_is_clamped(self):
        channel = ProgressChannel()
        op = channel.start("x")
        self.assertEqual(channel.update(op, percent=150)["percent"], 100.0)
        self.assertEqual(channel.update(op, percent=-5)["percent"], 0.0)

    def test_unknown_operation_raises(self):
        channel = ProgressChannel()
        with self.assertRaises(KeyError):
            channel.get("nope")
        with self.assertRaises(KeyError):
            channel.update("nope", percent=1)

    def test_list_filters(self):
        channel = ProgressChannel()
        a = channel.start("backup")
        b = channel.start("migration")
        channel.complete(a)
        self.assertEqual([op["operation_id"] for op in channel.list(kind="migration")], [b])
        self.assertEqual([op["operation_id"] for op in channel.list(active_only=True)], [b])

    def test_long_poll_wakes_on_update(self):
        channel = ProgressChannel()
        op = channel.start("migration")
        results = []

        def poller():
            results.append(channel.wait_for_change(op, since_version=0, timeout=10))

        thread = threading.Thread(target=poller)
        thread.start()
        time.sleep(0.1)
        channel.update(op, percent=10)
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results[0]["percent"], 10.0)

    def test_long_poll_returns_immediately_when_newer(self):
        channel = ProgressChannel()
        op = channel.start("migration")
        channel.update(op, percent=10)
        start = time.monotonic()
        state = channel.wait_for_change(op, since_version=0, timeout=10)
        self.assertLess(time.monotonic() - start, 1.0)
        self.assertEqual(state["version"], 1)

    def test_long_poll_times_out_with_current_state(self):
        channel = ProgressChannel()
        op = channel.start("migration")
        channel.update(op, percent=5)
        start = time.monotonic()
        state = channel.wait_for_change(op, since_version=99, timeout=0.2)
        self.assertGreaterEqual(time.monotonic() - start, 0.15)
        self.assertEqual(state["percent"], 5.0)

    def test_finished_history_is_bounded(self):
        from hypergery_ubuntu.v1 import progress as progress_module

        channel = ProgressChannel()
        ids = []
        for i in range(progress_module.FINISHED_HISTORY_LIMIT + 5):
            op = channel.start("x", operation_id=f"op-{i}")
            channel.complete(op)
            ids.append(op)
        with self.assertRaises(KeyError):
            channel.get(ids[0])
        channel.get(ids[-1])


def _phase(name, log, *, fail=False, rollback_fail=False, touches_source=False, weight=1.0, on_run=None):
    def run(context):
        if on_run:
            on_run(context)
        log.append(("run", name))
        if fail:
            raise HyperGeryError(f"{name} exploded")

    def rollback(context):
        log.append(("rollback", name))
        if rollback_fail:
            raise RuntimeError(f"{name} rollback broken")

    return MigrationPhase(name=name, run=run, rollback=rollback, touches_source=touches_source, weight=weight)


class MigrationEngineTests(unittest.TestCase):
    def _engine(self, phases):
        return MigrationEngine(phases, channel=ProgressChannel())

    def test_happy_path_runs_phases_in_order(self):
        log = []
        engine = self._engine(
            [_phase("preflight", log), _phase("transfer", log), _phase("switchover", log), _phase("activate", log)]
        )
        result = engine.run()
        self.assertTrue(result.ok)
        self.assertEqual(result.status, "done")
        self.assertEqual([entry for entry in log if entry[0] == "run"],
                         [("run", "preflight"), ("run", "transfer"), ("run", "switchover"), ("run", "activate")])
        self.assertEqual(result.rolled_back_phases, [])
        state = engine.channel.get(result.operation_id)
        self.assertEqual(state["status"], "done")
        self.assertEqual(state["percent"], 100.0)

    def test_failure_rolls_back_completed_phases_in_reverse(self):
        log = []
        engine = self._engine(
            [_phase("preflight", log), _phase("transfer", log), _phase("switchover", log, fail=True)]
        )
        result = engine.run()
        self.assertFalse(result.ok)
        self.assertEqual(result.status, "failed")
        self.assertIn("switchover exploded", result.error)
        self.assertEqual(result.completed_phases, ["preflight", "transfer"])
        rollbacks = [name for kind, name in log if kind == "rollback"]
        self.assertEqual(rollbacks, ["transfer", "preflight"], "rollback en orden inverso")
        self.assertEqual(engine.channel.get(result.operation_id)["status"], "failed")

    def test_rollback_errors_never_mask_the_original_failure(self):
        log = []
        engine = self._engine(
            [_phase("preflight", log, rollback_fail=True), _phase("transfer", log, fail=True)]
        )
        result = engine.run()
        self.assertIn("transfer exploded", result.error)
        self.assertEqual(result.rollback_errors, ["preflight: preflight rollback broken"])

    def test_source_mutation_before_switchover_is_rejected_at_construction(self):
        with self.assertRaises(HyperGeryError):
            MigrationEngine(
                [_phase("preflight", []), _phase("transfer", [], touches_source=True)],
                channel=ProgressChannel(),
            )

    def test_source_mutation_from_switchover_is_allowed(self):
        engine = MigrationEngine(
            [_phase("preflight", []), _phase("switchover", [], touches_source=True)],
            channel=ProgressChannel(),
        )
        self.assertTrue(engine.run().ok)

    def test_phases_out_of_order_are_rejected(self):
        with self.assertRaises(HyperGeryError):
            self._engine([_phase("transfer", []), _phase("preflight", [])])
        with self.assertRaises(HyperGeryError):
            self._engine([_phase("preflight", []), _phase("preflight", [])])
        with self.assertRaises(HyperGeryError):
            self._engine([MigrationPhase(name="explode", run=lambda c: None)])

    def test_cancel_between_phases_triggers_rollback(self):
        log = []
        engine = self._engine(
            [
                _phase("preflight", log, on_run=lambda c: None),
                _phase("transfer", log, on_run=lambda c: engine.request_cancel()),
                _phase("switchover", log),
            ]
        )
        result = engine.run()
        self.assertFalse(result.ok)
        self.assertEqual(result.status, "cancelled")
        runs = [name for kind, name in log if kind == "run"]
        self.assertEqual(runs, ["preflight", "transfer"], "switchover nunca llega a ejecutarse")
        rollbacks = [name for kind, name in log if kind == "rollback"]
        self.assertEqual(rollbacks, ["transfer", "preflight"])
        self.assertEqual(engine.channel.get(result.operation_id)["status"], "cancelled")

    def test_progress_reports_phase_and_weighted_percent(self):
        channel = ProgressChannel()
        log = []
        engine = MigrationEngine(
            [
                _phase("preflight", log, weight=1.0),
                _phase("transfer", log, weight=3.0),
            ],
            channel=channel,
        )
        result = engine.run()
        state = channel.get(result.operation_id)
        self.assertEqual(state["status"], "done")
        self.assertEqual(state["percent"], 100.0)

    def test_in_phase_report_callback_updates_metrics(self):
        channel = ProgressChannel()
        seen = {}

        def transfer_run(context):
            context["report"]("copiando RAM", fraction=0.5, metrics={"pages": 1234, "speed_mbps": 800})
            seen.update(channel.get(context["operation_id"]))

        engine = MigrationEngine(
            [MigrationPhase(name="transfer", run=transfer_run)],
            channel=channel,
        )
        result = engine.run()
        self.assertTrue(result.ok)
        self.assertEqual(seen["phase"], "transfer")
        self.assertEqual(seen["percent"], 50.0)
        self.assertEqual(seen["metrics"], {"pages": 1234, "speed_mbps": 800})


if __name__ == "__main__":
    unittest.main()
