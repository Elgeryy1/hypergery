"""TD-3 JobManager, HG-BUG-0008 closeEvent y HG-BUG-0015 throttle de preview."""

from __future__ import annotations

import importlib.util
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

HAS_PYSIDE6 = importlib.util.find_spec("PySide6") is not None

if HAS_PYSIDE6:
    from PySide6.QtWidgets import QApplication


def _app() -> "QApplication":
    return QApplication.instance() or QApplication([])


def _drain_events(app: "QApplication") -> None:
    for _ in range(5):
        app.processEvents()


@unittest.skipUnless(HAS_PYSIDE6, "PySide6 not installed — run inside the project venv")
class JobManagerTests(unittest.TestCase):
    def test_submit_runs_fn_and_delivers_success_with_result(self):
        app = _app()
        from hypergery_ubuntu.ui_qt.jobs import JobManager

        manager = JobManager()
        results = []
        job = manager.submit("ok", lambda: 41 + 1, on_success=lambda j: results.append(j.result))
        self.assertTrue(job.wait(5000))
        _drain_events(app)
        self.assertEqual(results, [42])
        self.assertEqual(manager.active, [])
        self.assertEqual([j.label for j in manager.completed], ["ok"])

    def test_failure_callback_carries_error_message(self):
        app = _app()
        from hypergery_ubuntu.ui_qt.jobs import JobManager

        def boom():
            raise RuntimeError("kaput")

        manager = JobManager()
        errors = []
        job = manager.submit("bad", boom, on_failure=lambda j: errors.append(j.error_message))
        self.assertTrue(job.wait(5000))
        _drain_events(app)
        self.assertEqual(errors, ["kaput"])

    def test_history_is_bounded(self):
        app = _app()
        from hypergery_ubuntu.ui_qt.jobs import JobManager

        manager = JobManager(history_limit=3)
        for i in range(5):
            job = manager.submit(f"job{i}", lambda: None)
            self.assertTrue(job.wait(5000))
            _drain_events(app)
        self.assertEqual([j.label for j in manager.completed], ["job2", "job3", "job4"])

    def test_untracked_jobs_stay_out_of_history(self):
        app = _app()
        from hypergery_ubuntu.ui_qt.jobs import JobManager

        manager = JobManager()
        job = manager.submit("preview:x", lambda: None, track_history=False)
        self.assertTrue(job.wait(5000))
        _drain_events(app)
        self.assertEqual(manager.completed, [])

    def test_cancel_suppresses_callbacks(self):
        app = _app()
        from hypergery_ubuntu.ui_qt.jobs import JobManager

        release = threading.Event()
        called = []
        manager = JobManager()
        job = manager.submit(
            "slow",
            release.wait,
            on_success=lambda j: called.append("success"),
            on_finished=lambda j: called.append("finished"),
        )
        job.cancel()
        release.set()
        self.assertTrue(job.wait(5000))
        _drain_events(app)
        self.assertEqual(called, [])
        self.assertEqual(manager.active, [])

    def test_shutdown_reports_jobs_that_outlive_the_bounded_wait(self):
        app = _app()
        from hypergery_ubuntu.ui_qt.jobs import JobManager

        release = threading.Event()
        called = []
        manager = JobManager()
        job = manager.submit("stuck", release.wait, on_success=lambda j: called.append("success"))
        try:
            survivors = manager.shutdown(timeout_ms=100)
            self.assertEqual(survivors, ["stuck"])
        finally:
            release.set()
            self.assertTrue(job.wait(5000))
        _drain_events(app)
        # Callbacks quedan suprimidos tras el shutdown aunque el job termine.
        self.assertEqual(called, [])

    def test_shutdown_with_idle_manager_is_instant_and_empty(self):
        _app()
        from hypergery_ubuntu.ui_qt.jobs import JobManager

        self.assertEqual(JobManager().shutdown(timeout_ms=1), [])


@unittest.skipUnless(HAS_PYSIDE6, "PySide6 not installed — run inside the project venv")
class MainWindowCloseEventTests(unittest.TestCase):
    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_close_event_shuts_down_job_manager(self, backend_cls):
        _app()
        from hypergery_ubuntu.ui_qt.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            backend_cls.return_value.data_dir = Path(tmp) / "hypergery"
            window = MainWindow()
            with patch.object(window.job_manager, "shutdown", return_value=[]) as shutdown:
                window.close()
            shutdown.assert_called_once_with(timeout_ms=MainWindow.CLOSE_WAIT_MS)

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_close_event_waits_bounded_for_running_jobs(self, backend_cls):
        app = _app()
        from hypergery_ubuntu.ui_qt.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            backend_cls.return_value.data_dir = Path(tmp) / "hypergery"
            window = MainWindow()
            window.CLOSE_WAIT_MS = 100
            release = threading.Event()
            job = window.job_manager.submit("uat-u2", release.wait)
            try:
                window.close()  # no cuelga: espera acotada (U2)
                self.assertTrue(window.job_manager.closing)
            finally:
                release.set()
                self.assertTrue(job.wait(5000))
            _drain_events(app)


@unittest.skipUnless(HAS_PYSIDE6, "PySide6 not installed — run inside the project venv")
class PreviewThrottleTests(unittest.TestCase):
    def _window(self, backend_cls, tmp):
        from hypergery_ubuntu.ui_qt.main_window import MainWindow

        backend_cls.return_value.data_dir = Path(tmp) / "hypergery"
        window = MainWindow()
        window._fake_now = 1000.0
        window._preview_clock = lambda: window._fake_now
        return window

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_rapid_requests_spawn_one_capture_and_one_retry(self, backend_cls):
        _app()
        with tempfile.TemporaryDirectory() as tmp:
            window = self._window(backend_cls, tmp)
            captures = []
            retries = []
            with (
                patch.object(window, "_start_preview_capture", side_effect=captures.append),
                patch.object(
                    window,
                    "_schedule_preview_retry",
                    side_effect=lambda name, delay_ms: retries.append((name, delay_ms)),
                ),
            ):
                for _ in range(5):
                    window._throttled_capture("dc01")
                    window._preview_inflight.discard("dc01")
            self.assertEqual(captures, ["dc01"])
            self.assertEqual(len(retries), 1)
            self.assertEqual(retries[0][0], "dc01")
            window.close()

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_capture_allowed_again_after_cooldown(self, backend_cls):
        _app()
        with tempfile.TemporaryDirectory() as tmp:
            window = self._window(backend_cls, tmp)
            captures = []
            with patch.object(window, "_start_preview_capture", side_effect=captures.append):
                window._throttled_capture("dc01")
                window._preview_inflight.discard("dc01")
                window._fake_now += window.PREVIEW_MIN_INTERVAL_S + 0.1
                window._throttled_capture("dc01")
            self.assertEqual(captures, ["dc01", "dc01"])
            window.close()

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_inflight_capture_blocks_new_ones(self, backend_cls):
        _app()
        with tempfile.TemporaryDirectory() as tmp:
            window = self._window(backend_cls, tmp)
            captures = []
            with patch.object(window, "_start_preview_capture", side_effect=captures.append):
                window._throttled_capture("dc01")
                window._fake_now += window.PREVIEW_MIN_INTERVAL_S + 0.1
                window._throttled_capture("dc01")  # sigue en vuelo → no capture
            self.assertEqual(captures, ["dc01"])
            window.close()

    @patch("hypergery_ubuntu.ui_qt.main_window.HyperGeryBackend")
    def test_retry_only_fires_for_still_selected_vm(self, backend_cls):
        _app()
        with tempfile.TemporaryDirectory() as tmp:
            window = self._window(backend_cls, tmp)
            captured = []
            with patch.object(window, "_capture_preview", side_effect=captured.append):
                window._preview_target = "other"
                window._preview_retry_pending.add("dc01")
                window._run_preview_retry("dc01")
                self.assertEqual(captured, [])
                window._preview_target = "dc01"
                window._run_preview_retry("dc01")
                self.assertEqual(captured, ["dc01"])
            self.assertNotIn("dc01", window._preview_retry_pending)
            window.close()


if __name__ == "__main__":
    unittest.main()
