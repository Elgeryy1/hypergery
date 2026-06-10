"""Regression tests for the non-blocking VNC console connect.

The integrated VNC viewer used to open its TCP socket on the UI thread with no
timeout, freezing the whole app when the host/VM was unreachable. These tests
prove the connect now runs on a worker with a hard timeout and that an
unreachable host surfaces a retryable error instead of blocking.
"""

from __future__ import annotations

import os
import socket
import time
import unittest
from unittest.mock import MagicMock

import pytest

pytest.importorskip("PySide6")

# Headless Qt: must be set before any QApplication is created.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEventLoop, QThread, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from hypergery_ubuntu.ui_qt.console import VmConsoleWindow, VncConnectWorker  # noqa: E402
from hypergery_ubuntu.ui_qt.console_helpers import (  # noqa: E402
    VNC_CONNECT_TIMEOUT,
    VNC_FAILED_MESSAGE,
    blocking_vnc_connect,
    vnc_connect_error_reason,
)


# 127.0.0.1:1 is a privileged, normally-closed port: connecting to it fails fast
# with "connection refused" without ever touching the network.
CLOSED_HOST = "127.0.0.1"
CLOSED_PORT = 1


def _drain_events(loop_ms: int = 50) -> None:
    QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, loop_ms)


class BlockingConnectHelperTests(unittest.TestCase):
    """Pure-logic tests: no Qt objects, so no platform needed."""

    def test_connect_to_closed_port_fails_fast(self):
        start = time.monotonic()
        with self.assertRaises(OSError):
            blocking_vnc_connect(CLOSED_HOST, CLOSED_PORT, timeout=2.0)
        # Connection refused is immediate; nowhere near the 10 s UI timeout.
        self.assertLess(time.monotonic() - start, 5.0)

    def test_connect_timeout_is_ten_seconds(self):
        self.assertEqual(VNC_CONNECT_TIMEOUT, 10.0)

    def test_timeout_maps_to_spanish_reason(self):
        reason = vnc_connect_error_reason(TimeoutError())
        self.assertIn("tiempo de espera", reason)
        self.assertIn("10", reason)

    def test_generic_error_reason_falls_back_to_detail(self):
        self.assertEqual(
            vnc_connect_error_reason(OSError("connection refused")),
            "connection refused",
        )

    def test_successful_connect_returns_descriptor(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        host, port = server.getsockname()
        try:
            fd = blocking_vnc_connect(host, port, timeout=2.0)
            self.assertIsInstance(fd, int)
            self.assertGreaterEqual(fd, 0)
            # Adopt the returned descriptor to confirm it is a live, usable socket.
            adopted = socket.socket(fileno=fd)
            try:
                self.assertEqual(adopted.getpeername()[1], port)
            finally:
                adopted.close()
        finally:
            server.close()


@unittest.skipUnless(
    QApplication is not None, "PySide6 not installed — run inside the project venv"
)
class VncConnectWorkerTests(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])

    def test_worker_run_reports_failure_for_unreachable_host(self):
        """Calling run() directly (no thread) must emit failed, not block."""
        worker = VncConnectWorker(CLOSED_HOST, CLOSED_PORT, timeout=2.0)
        results: dict[str, object] = {}
        worker.connected.connect(lambda fd: results.setdefault("connected", fd))
        worker.failed.connect(lambda reason: results.setdefault("failed", reason))
        worker.timed_out.connect(lambda: results.setdefault("timed_out", True))

        start = time.monotonic()
        worker.run()
        elapsed = time.monotonic() - start

        self.assertLess(elapsed, 5.0, "connect to closed port should not block")
        self.assertNotIn("connected", results)
        # Either an explicit refusal (failed) or a timeout — never a hang.
        self.assertTrue("failed" in results or "timed_out" in results)

    def test_worker_on_real_thread_finishes_without_blocking(self):
        """End-to-end: worker on its own QThread emits a terminal signal."""
        thread = QThread()
        worker = VncConnectWorker(CLOSED_HOST, CLOSED_PORT, timeout=2.0)
        worker.moveToThread(thread)
        outcome: dict[str, object] = {}
        thread.started.connect(worker.run)
        worker.connected.connect(lambda fd: outcome.setdefault("result", ("connected", fd)))
        worker.failed.connect(lambda reason: outcome.setdefault("result", ("failed", reason)))
        worker.timed_out.connect(lambda: outcome.setdefault("result", ("timed_out", None)))
        worker.finished.connect(thread.quit)

        thread.start()

        # Spin the event loop until the thread finishes or a generous deadline.
        deadline = time.monotonic() + 8.0
        while thread.isRunning() and time.monotonic() < deadline:
            _drain_events()
        thread.wait(2000)

        self.assertFalse(thread.isRunning(), "worker thread should have finished")
        self.assertIn("result", outcome)
        self.assertNotEqual(outcome["result"][0], "connected")


@unittest.skipUnless(
    QApplication is not None, "PySide6 not installed — run inside the project venv"
)
class ConsoleConnectUiTests(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])

    def _make_vnc_window(self):
        from hypergery_ubuntu.backend import VmSummary

        backend = MagicMock()
        backend.get_console_display.return_value = {
            "type": "vnc",
            "host": CLOSED_HOST,
            "port": CLOSED_PORT,
            "display": ":0",
            "uri": f"vnc://{CLOSED_HOST}:{CLOSED_PORT}",
        }
        vm = VmSummary(
            name="hg-vnc-unreachable",
            state="running",
            lab_id="lab",
            ram_mib=1024,
            vcpus=1,
            graphics="vnc",
        )
        return VmConsoleWindow(backend, vm), backend

    def test_constructor_signature_unchanged(self):
        """main_window.py builds the window positionally with an on_vm_changed kwarg."""
        from hypergery_ubuntu.backend import VmSummary

        backend = MagicMock()
        vm = VmSummary(name="hg", state="shut off", lab_id="lab", ram_mib=512, vcpus=1, graphics="vnc")
        callback = lambda name: None  # noqa: E731 - terse stub for identity check.
        window = VmConsoleWindow(backend, vm, None, on_vm_changed=callback)
        # The callback is stored verbatim; the public 4-arg signature still holds.
        self.assertIs(window.on_vm_changed, callback)
        window.close()

    def test_connect_runs_off_thread_and_does_not_freeze(self):
        window, _backend = self._make_vnc_window()
        try:
            start = time.monotonic()
            window.console.connect_console()
            # connect_console must return immediately; the connect is on a worker.
            self.assertLess(time.monotonic() - start, 1.0)
            self.assertTrue(window.console.connecting)
            self.assertIsNotNone(window.console.connect_thread)
            # While connecting, the Connect action is disabled and Disconnect cancels.
            self.assertFalse(window.connect_action.isEnabled())
            self.assertTrue(window.disconnect_action.isEnabled())
        finally:
            window.console.disconnect_console()
            window.close()

    def test_unreachable_host_shows_error_card_with_retry(self):
        window, _backend = self._make_vnc_window()
        try:
            window.console.connect_console()
            # Pump the event loop until the worker reports back or we hit a deadline.
            deadline = time.monotonic() + 8.0
            while window.console.connecting and time.monotonic() < deadline:
                _drain_events()
            self.assertFalse(window.console.connecting, "worker never reported back")

            # The error card (not the live screen) is shown, with a Reintentar button.
            self.assertIs(
                window.console.mode_stack.currentWidget(), window.console.error_card
            )
            self.assertEqual(window.console.retry_button.text(), "Reintentar")
            self.assertIn(VNC_FAILED_MESSAGE, window.state_label.text())
            # Not connected; no input capture leaked through.
            self.assertFalse(window.console.is_connected())
            self.assertFalse(window.console.input_captured)
            # Reconnect (Reintentar) is wired and restarts a worker without crashing.
            window.console.retry_button.click()
            self.assertTrue(window.console.connecting)
        finally:
            window.console.disconnect_console()
            window.close()

    def test_disconnect_cancels_in_flight_connect(self):
        window, _backend = self._make_vnc_window()
        try:
            window.console.connect_console()
            self.assertTrue(window.console.connecting)
            window.console.disconnect_console()
            # After cancel, no worker thread remains and we are idle, not connected.
            self.assertFalse(window.console.connecting)
            self.assertIsNone(window.console.connect_thread)
            self.assertFalse(window.console.is_connected())
        finally:
            window.close()

    def test_cancel_does_not_block_ui_while_connect_hangs(self):
        """HG-BUG-0014: cancelar con el connect colgado debe volver al instante
        (antes: hasta 10 s de UI congelada en thread.wait())."""
        import threading

        from hypergery_ubuntu.ui_qt import console as console_mod

        started = threading.Event()
        release = threading.Event()

        def hanging_connect(host, port, timeout):
            started.set()
            release.wait(5.0)
            raise OSError("connect aborted by test")

        original = console_mod.blocking_vnc_connect
        console_mod.blocking_vnc_connect = hanging_connect
        try:
            window, _backend = self._make_vnc_window()
            try:
                window.console.connect_console()
                self.assertTrue(started.wait(2.0), "worker never started")

                begin = time.monotonic()
                window.console.disconnect_console()
                elapsed = time.monotonic() - begin

                self.assertLess(elapsed, 0.5, "cancel must not block the UI thread")
                self.assertFalse(window.console.connecting)
                self.assertIsNone(window.console.connect_thread)
                # The cancelled thread keeps draining in the background…
                self.assertEqual(len(window.console._draining_threads), 1)

                # …and once the blocking connect returns, it cleans itself up.
                release.set()
                deadline = time.monotonic() + 5.0
                while window.console._draining_threads and time.monotonic() < deadline:
                    _drain_events()
                self.assertEqual(
                    len(window.console._draining_threads), 0, "drained thread not reaped"
                )
            finally:
                release.set()
                window.close()
        finally:
            console_mod.blocking_vnc_connect = original


if __name__ == "__main__":
    unittest.main()
