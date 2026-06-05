import json
import tempfile
import unittest
from pathlib import Path

from hypergery_ubuntu.v1.errors import HostOfflineError
from hypergery_ubuntu.v1.hosts import HOST_CAPABILITIES, HOST_ROLES, HostInfo, HostRegistry, loopback_host
from hypergery_ubuntu.v1.settings import V1Settings
from hypergery_ubuntu.v1.telemetry import (
    TelemetrySample,
    TelemetryService,
    evaluate_alerts,
    read_battery,
    read_disk_mib,
    read_memory_mib,
)


def fake_battery_dir(tmp: Path, percent: int = 42, status: str = "Discharging") -> Path:
    battery = tmp / "BAT0"
    battery.mkdir(parents=True)
    (battery / "capacity").write_text(f"{percent}\n", encoding="utf-8")
    (battery / "status").write_text(f"{status}\n", encoding="utf-8")
    return tmp


class TelemetryReaderTests(unittest.TestCase):
    def test_memory_and_disk_readers_return_positive_values(self):
        total, available = read_memory_mib()
        self.assertGreater(total, 0)
        self.assertGreaterEqual(total, available)
        disk_total, disk_free = read_disk_mib("/")
        self.assertGreater(disk_total, 0)
        self.assertGreaterEqual(disk_total, disk_free)

    def test_battery_reader_uses_sysfs_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            supply = fake_battery_dir(Path(tmp), percent=37, status="Not charging")
            percent, status = read_battery(supply)
        self.assertEqual(percent, 37)
        self.assertEqual(status, "not_charging")

    def test_battery_reader_handles_missing_battery(self):
        with tempfile.TemporaryDirectory() as tmp:
            percent, status = read_battery(Path(tmp) / "missing")
        # On battery-less dirs the sysfs path yields nothing; psutil fallback
        # may still report a real battery on laptops, so only check contract.
        self.assertTrue(percent is None or 0 <= percent <= 100)
        self.assertIsInstance(status, str)


class TelemetryServiceTests(unittest.TestCase):
    def make_service(self, tmp: Path, **settings_kwargs) -> TelemetryService:
        return TelemetryService(
            settings=V1Settings(**settings_kwargs),
            history_path=tmp / "history.json",
            host_id="laptop",
            power_supply_dir=fake_battery_dir(tmp / "power", percent=55),
            disk_path="/",
        )

    def test_sample_local_collects_all_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.make_service(Path(tmp))
            sample = service.sample_local()
        self.assertEqual(sample.host_id, "laptop")
        self.assertGreater(sample.ram_total_mib, 0)
        self.assertGreater(sample.disk_total_mib, 0)
        self.assertEqual(sample.battery_percent, 55)
        self.assertEqual(sample.source, "local")
        self.assertGreaterEqual(sample.uptime_seconds, 0)

    def test_history_keeps_last_n_samples(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.make_service(Path(tmp), telemetry_history_samples=3)
            for index in range(5):
                service.record(TelemetrySample(timestamp=f"t{index}", host_id="laptop"))
            history = service.history("laptop")
        self.assertEqual(len(history), 3)
        self.assertEqual(history[0]["timestamp"], "t2")
        self.assertEqual(history[-1]["timestamp"], "t4")

    def test_concurrent_record_keeps_all_samples(self):
        import threading

        with tempfile.TemporaryDirectory() as tmp:
            service = self.make_service(Path(tmp), telemetry_history_samples=1000)

            def writer(n):
                for i in range(25):
                    service.record(TelemetrySample(timestamp=f"{n}-{i}", host_id=f"host{n % 2}"))

            threads = [threading.Thread(target=writer, args=(n,)) for n in range(6)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            total = sum(len(samples) for samples in [service.history("host0"), service.history("host1")])
        self.assertEqual(total, 6 * 25)

    def test_remote_sample_marks_stale_hosts(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.make_service(Path(tmp))
            fresh = service.remote_sample(
                {"host_id": "pc", "status": "online", "last_seen": service.sample_local().timestamp, "ram_total_mib": 16384, "ram_free_mib": 8192}
            )
            old = service.remote_sample({"host_id": "pc", "status": "online", "last_seen": "2020-01-01T00:00:00+00:00"})
            offline = service.remote_sample({"host_id": "pc", "status": "offline", "last_seen": fresh.timestamp})
        self.assertFalse(fresh.stale)
        self.assertEqual(fresh.ram_used_mib, 8192)
        self.assertTrue(old.stale)
        self.assertTrue(offline.stale)


class AlertTests(unittest.TestCase):
    def sample(self, **kwargs) -> TelemetrySample:
        base = {
            "host_id": "laptop",
            "ram_total_mib": 16384,
            "ram_free_mib": 8192,
            "disk_total_mib": 100000,
            "disk_free_mib": 50000,
            "battery_percent": 80,
            "battery_status": "discharging",
        }
        base.update(kwargs)
        return TelemetrySample(**base)

    def kinds(self, alerts):
        return {alert["kind"] for alert in alerts}

    def test_healthy_sample_produces_no_alerts(self):
        self.assertEqual(evaluate_alerts(local_sample=self.sample()), [])

    def test_ram_and_disk_thresholds(self):
        alerts = evaluate_alerts(local_sample=self.sample(ram_free_mib=512, disk_free_mib=1024))
        self.assertEqual(self.kinds(alerts), {"ram_low", "disk_low"})

    def test_battery_tiers(self):
        self.assertIn("battery_eco", self.kinds(evaluate_alerts(local_sample=self.sample(battery_percent=45))))
        self.assertIn("battery_low", self.kinds(evaluate_alerts(local_sample=self.sample(battery_percent=25))))
        self.assertIn("battery_emergency", self.kinds(evaluate_alerts(local_sample=self.sample(battery_percent=15))))
        self.assertIn("battery_critical", self.kinds(evaluate_alerts(local_sample=self.sample(battery_percent=5))))

    def test_charging_battery_does_not_alert(self):
        alerts = evaluate_alerts(local_sample=self.sample(battery_percent=5, battery_status="charging"))
        self.assertEqual(alerts, [])

    def test_host_offline_and_nas_alerts(self):
        with tempfile.TemporaryDirectory() as tmp:
            alerts = evaluate_alerts(
                hub_hosts=[{"host_id": "pc", "status": "offline"}, {"host_id": "lenovo", "status": "online"}],
                nas_path=Path(tmp) / "missing-mount",
            )
        self.assertEqual(self.kinds(alerts), {"host_offline", "nas_offline"})
        offline = [alert for alert in alerts if alert["kind"] == "host_offline"]
        self.assertEqual(len(offline), 1)
        self.assertEqual(offline[0]["host"], "pc")

    def test_writable_nas_does_not_alert(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(evaluate_alerts(nas_path=tmp), [])


class FakeHubClient:
    def __init__(self, hosts=None, error=None):
        self.hosts = hosts or []
        self.error = error

    def list_hosts(self):
        if self.error:
            raise self.error
        return list(self.hosts)


class HostRegistryTests(unittest.TestCase):
    def make_registry(self, tmp: Path, **kwargs) -> HostRegistry:
        telemetry = TelemetryService(
            settings=kwargs.get("settings") or V1Settings(),
            history_path=tmp / "history.json",
            host_id="laptop",
            power_supply_dir=fake_battery_dir(tmp / "power"),
        )
        kwargs.setdefault("telemetry", telemetry)
        return HostRegistry(**kwargs)

    def test_local_host_role_and_capabilities(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = self.make_registry(Path(tmp))
            local = registry.local_host()
        self.assertEqual(local.id, "laptop")
        self.assertEqual(local.role, "laptop")  # battery present → laptop
        self.assertIn("can_report_battery", local.capabilities)
        self.assertIn("can_run_vms", local.capabilities)
        self.assertEqual(local.status, "online")

    def test_list_hosts_merges_hub_and_skips_local_duplicate(self):
        hub = FakeHubClient(
            hosts=[
                {"host_id": "laptop", "status": "online"},
                {"host_id": "pc-casa", "status": "offline", "hostname": "pc.lan", "ram_total_mib": 32768},
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            registry = self.make_registry(Path(tmp), hub_client=hub, role_overrides={"pc-casa": "home_pc"})
            hosts = registry.list_hosts()
        ids = [host.id for host in hosts]
        self.assertEqual(ids, ["laptop", "pc-casa"])
        pc = hosts[1]
        self.assertEqual(pc.role, "home_pc")
        self.assertEqual(pc.status, "offline")
        self.assertIn("hub", pc.tags)

    def test_hub_failure_degrades_to_local_only(self):
        hub = FakeHubClient(error=ConnectionError("hub down"))
        with tempfile.TemporaryDirectory() as tmp:
            registry = self.make_registry(Path(tmp), hub_client=hub)
            hosts = registry.list_hosts()
        self.assertEqual([host.id for host in hosts], ["laptop"])

    def test_offline_mode_skips_hub_entirely(self):
        hub = FakeHubClient(hosts=[{"host_id": "pc-casa", "status": "online"}])
        with tempfile.TemporaryDirectory() as tmp:
            registry = self.make_registry(Path(tmp), hub_client=hub, settings=V1Settings(offline_mode=True))
            hosts = registry.list_hosts()
            health = registry.health_check(HostInfo(id="pc-casa", status="online", tags=["hub"]))
        self.assertEqual([host.id for host in hosts], ["laptop"])
        self.assertFalse(health["reachable"])
        self.assertEqual(health["source"], "offline_mode")

    def test_loopback_host_for_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = self.make_registry(Path(tmp), include_loopback=True)
            hosts = registry.list_hosts()
        self.assertIn("loopback", [host.id for host in hosts])
        loop = loopback_host()
        self.assertEqual(loop.status, "online")
        self.assertIn("experimental", loop.capabilities)

    def test_get_host_raises_host_offline_error_for_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = self.make_registry(Path(tmp))
            with self.assertRaises(HostOfflineError):
                registry.get_host("ghost-host")

    def test_invalid_role_and_capabilities_are_sanitized(self):
        host = HostInfo(id="x", role="mainframe", capabilities=["can_run_vms", "can_fly"])
        self.assertEqual(host.role, "unknown")
        self.assertEqual(host.capabilities, ["can_run_vms"])
        self.assertIn("laptop", HOST_ROLES)
        self.assertIn("can_act_as_hub", HOST_CAPABILITIES)

    def test_health_check_uses_agent_url_when_present(self):
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps({"ok": True}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                return

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                registry = self.make_registry(Path(tmp))
                host = HostInfo(
                    id="agent-host",
                    status="unknown",
                    agent_url=f"http://127.0.0.1:{server.server_address[1]}",
                    tags=["hub"],
                )
                health = registry.health_check(host)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        self.assertTrue(health["reachable"])
        self.assertEqual(health["status"], "online")
        self.assertEqual(health["body"], {"ok": True})
        self.assertIsNotNone(health["latency_ms"])


if __name__ == "__main__":
    unittest.main()
