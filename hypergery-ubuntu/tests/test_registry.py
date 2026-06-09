from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from hypergery_ubuntu.backend import HyperGeryError
from hypergery_ubuntu.registry import RegistryServer, RegistryStore
from hypergery_ubuntu.registry.server import cleanup_staged_packages, list_staged_packages


class RegistryStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RegistryStore(Path(self.tmp.name) / "registry.sqlite3", offline_timeout_seconds=0)

    def tearDown(self):
        self.tmp.cleanup()

    def test_host_register_and_heartbeat(self):
        host = self.store.register_host({
            "host_id": "pc-casa",
            "name": "PC Casa",
            "hostname": "pc-casa.local",
            "kvm_ok": True,
            "libvirt_ok": True,
            "active_vms": ["vm1"],
        })
        self.assertEqual(host["host_id"], "pc-casa")
        self.assertTrue(host["kvm_ok"])
        self.assertEqual(host["active_vms"], ["vm1"])

        updated = self.store.heartbeat({
            "host_id": "pc-casa",
            "name": "PC Casa",
            "hostname": "pc-casa.local",
            "active_vms": ["vm1", "vm2"],
        })
        self.assertEqual(updated["active_vms"], ["vm1", "vm2"])

    def test_offline_detection_does_not_delete_host(self):
        self.store.register_host({"host_id": "slow-host", "hostname": "slow-host"})
        time.sleep(0.01)
        host = self.store.get_host("slow-host")
        self.assertEqual(host["status"], "offline")
        self.assertEqual(len(self.store.list_hosts()), 1)

    def test_command_queue_allowlist_and_result(self):
        self.store.register_host({"host_id": "target", "hostname": "target"})
        command = self.store.create_command({
            "target_host_id": "target",
            "command_type": "ping",
            "payload": {"hello": "world"},
        })
        self.assertEqual(command["status"], "pending")
        pending = self.store.pending_commands_for_host("target")
        self.assertEqual([item["command_id"] for item in pending], [command["command_id"]])

        done = self.store.set_command_result(command["command_id"], {"status": "done", "result": {"pong": True}})
        self.assertEqual(done["status"], "done")
        self.assertEqual(done["result"], {"pong": True})
        self.assertEqual(self.store.pending_commands_for_host("target"), [])

        with self.assertRaises(HyperGeryError):
            self.store.create_command({"target_host_id": "target", "command_type": "shell", "payload": {}})

    def test_vm_inventory_report_and_list(self):
        self.store.register_host({"host_id": "local", "hostname": "localhost"})
        report = self.store.report_vms(
            {
                "host_id": "local",
                "vms": [
                    {
                        "vm_name": "hg-test",
                        "state": "running",
                        "lab_id": "lab1",
                        "display": "vnc",
                        "ram_mib": 2048,
                        "vcpus": 2,
                        "disk_paths": ["/mnt/hypergery-nas/hypergery/vms/hg-test.qcow2"],
                        "iso_paths": [],
                    }
                ],
            }
        )
        self.assertEqual(report["count"], 1)
        self.assertEqual(self.store.get_host("local")["active_vms"], ["hg-test"])
        vms = self.store.list_vms("local")
        self.assertEqual(vms[0]["vm_name"], "hg-test")
        self.assertEqual(vms[0]["display"], "vnc")
        self.assertEqual(vms[0]["disk_paths"], ["/mnt/hypergery-nas/hypergery/vms/hg-test.qcow2"])

    def test_vm_inventory_reports_networks_and_macs(self):
        self.store.register_host({"host_id": "local", "hostname": "localhost"})
        self.store.report_vms(
            {
                "host_id": "local",
                "vms": [
                    {
                        "vm_name": "hg-net",
                        "state": "running",
                        "networks": ["hg-net-lab1", "default"],
                        "macs": ["52:54:00:aa:bb:cc"],
                    },
                    {"vm_name": "hg-legacy", "state": "running"},
                ],
            }
        )
        vms = {vm["vm_name"]: vm for vm in self.store.list_vms("local")}
        self.assertEqual(vms["hg-net"]["networks"], ["hg-net-lab1", "default"])
        self.assertEqual(vms["hg-net"]["macs"], ["52:54:00:aa:bb:cc"])
        # Old agents that do not report the new fields still work.
        self.assertEqual(vms["hg-legacy"]["networks"], [])
        self.assertEqual(vms["hg-legacy"]["macs"], [])

    def test_list_commands_filters_and_limit(self):
        self.store.register_host({"host_id": "host-a", "hostname": "a"})
        self.store.register_host({"host_id": "host-b", "hostname": "b"})
        first = self.store.create_command({"target_host_id": "host-a", "command_type": "ping", "payload": {}})
        second = self.store.create_command({"target_host_id": "host-a", "command_type": "vm_start", "payload": {"vm_name": "vm1"}})
        third = self.store.create_command({"target_host_id": "host-b", "command_type": "vm_shutdown", "payload": {"vm_name": "vm2"}})
        self.store.set_command_result(second["command_id"], {"status": "done", "result": {"message": "started"}})

        everything = self.store.list_commands()
        self.assertEqual(len(everything), 3)

        host_a = self.store.list_commands(target_host_id="host-a")
        self.assertEqual({item["command_id"] for item in host_a}, {first["command_id"], second["command_id"]})

        done = self.store.list_commands(status="done")
        self.assertEqual([item["command_id"] for item in done], [second["command_id"]])
        self.assertEqual(done[0]["result"], {"message": "started"})

        starts = self.store.list_commands(command_type="vm_start")
        self.assertEqual([item["command_id"] for item in starts], [second["command_id"]])

        limited = self.store.list_commands(limit=1)
        self.assertEqual(len(limited), 1)

        combo = self.store.list_commands(target_host_id="host-b", status="pending")
        self.assertEqual([item["command_id"] for item in combo], [third["command_id"]])

        with self.assertRaises(HyperGeryError):
            self.store.list_commands(status="exploded")
        with self.assertRaises(HyperGeryError):
            self.store.list_commands(command_type="shell")
        with self.assertRaises(HyperGeryError):
            self.store.list_commands(limit="lots")

    def test_events_lifecycle(self):
        event = self.store.create_event({"kind": "hub", "message": "started", "payload": {"port": 8765}})
        self.assertEqual(event["kind"], "hub")
        self.assertEqual(event["payload"], {"port": 8765})
        self.assertEqual(self.store.list_events()[0]["event_id"], event["event_id"])

    def test_migration_status_lifecycle_accepts_remote_progress_states(self):
        payload = {
            "source_host_id": "source",
            "target_host_id": "target",
            "source_vm_name": "hg-source",
            "target_vm_name": "hg-target",
            "strategy": "nas_clone",
        }
        for status in ("preflight", "packaging", "uploaded", "waiting_target", "importing", "defining_vm", "done"):
            migration = self.store.update_migration_status("mig-1", {**payload, "status": status, "package_path": "/hypergery/migrations/mig-1"})
            self.assertEqual(migration["status"], status)
            self.assertEqual(migration["package_path"], "/hypergery/migrations/mig-1")
        failed = self.store.update_migration_status("mig-1", {**payload, "status": "failed", "errors": ["boom"]})
        self.assertEqual(failed["errors"], ["boom"])


class RegistryHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        store = RegistryStore(Path(self.tmp.name) / "registry.sqlite3")
        self.server = RegistryServer(("127.0.0.1", 0), store, auth_token="hgtest-token")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.base_url = f"http://{host}:{port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.tmp.cleanup()

    def request_json(self, method: str, path: str, payload: dict | None = None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = Request(self.base_url + path, data=data, method=method)
        req.add_header("Authorization", "Bearer hgtest-token")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        with urlopen(req, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_health_and_host_endpoints(self):
        status, health = self.request_json("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(health, {"ok": True})

        status, host = self.request_json("POST", "/hosts/register", {"host_id": "local", "hostname": "localhost"})
        self.assertEqual(status, 200)
        self.assertEqual(host["host_id"], "local")

        status, hosts = self.request_json("GET", "/hosts")
        self.assertEqual(status, 200)
        self.assertEqual(hosts["hosts"][0]["host_id"], "local")

    def test_command_endpoints(self):
        self.request_json("POST", "/hosts/register", {"host_id": "local", "hostname": "localhost"})
        status, command = self.request_json("POST", "/commands", {
            "target_host_id": "local",
            "command_type": "ping",
            "payload": {},
        })
        self.assertEqual(status, 201)

        status, queued = self.request_json("GET", "/commands/local")
        self.assertEqual(status, 200)
        self.assertEqual(queued["commands"][0]["command_id"], command["command_id"])

        status, result = self.request_json("POST", f"/commands/{command['command_id']}/result", {
            "status": "done",
            "result": {"pong": True},
        })
        self.assertEqual(status, 200)
        self.assertEqual(result["result"], {"pong": True})

        status, by_id = self.request_json("GET", f"/commands/id/{command['command_id']}")
        self.assertEqual(status, 200)
        self.assertEqual(by_id["command_id"], command["command_id"])

    def test_vm_migration_and_event_endpoints(self):
        self.request_json("POST", "/hosts/register", {"host_id": "local", "hostname": "localhost"})
        status, report = self.request_json(
            "POST",
            "/vms/report",
            {"host_id": "local", "vms": [{"vm_name": "hg-test", "state": "shutoff", "display": "spice"}]},
        )
        self.assertEqual(status, 200)
        self.assertEqual(report["count"], 1)

        status, vms = self.request_json("GET", "/vms/local")
        self.assertEqual(status, 200)
        self.assertEqual(vms["vms"][0]["vm_name"], "hg-test")

        status, migration = self.request_json(
            "POST",
            "/migrations",
            {
                "source_host_id": "source",
                "target_host_id": "local",
                "source_vm_name": "hg-source",
                "target_vm_name": "hg-target",
                "package_path": "/hypergery/migrations/mig-1",
            },
        )
        self.assertEqual(status, 201)
        self.assertEqual(migration["status"], "created")

        status, event = self.request_json("POST", "/events", {"kind": "test", "message": "ok"})
        self.assertEqual(status, 201)
        self.assertEqual(event["kind"], "test")

    def test_list_commands_endpoint_with_filters(self):
        from hypergery_ubuntu.registry import RegistryClient

        self.request_json("POST", "/hosts/register", {"host_id": "local", "hostname": "localhost"})
        client = RegistryClient(self.base_url, token="hgtest-token")
        ping = client.create_command("local", "ping", {})
        start = client.create_command("local", "vm_start", {"vm_name": "vm1"})
        client.set_command_result(start["command_id"], "failed", {"error": "boom"})

        commands = client.list_commands()
        self.assertEqual({item["command_id"] for item in commands}, {ping["command_id"], start["command_id"]})

        failed = client.list_commands(status="failed")
        self.assertEqual([item["command_id"] for item in failed], [start["command_id"]])
        self.assertEqual(failed[0]["result"], {"error": "boom"})

        typed = client.list_commands(command_type="ping", target_host_id="local")
        self.assertEqual([item["command_id"] for item in typed], [ping["command_id"]])

        limited = client.list_commands(limit=1)
        self.assertEqual(len(limited), 1)

        with self.assertRaises(HyperGeryError):
            client.list_commands(status="weird")

    def test_vm_power_command_helpers_queue_allowed_commands(self):
        from hypergery_ubuntu.registry import RegistryClient

        self.request_json("POST", "/hosts/register", {"host_id": "remote", "hostname": "remote"})
        client = RegistryClient(self.base_url, token="hgtest-token")
        queued = client.start_remote_vm("remote", "vm1")
        self.assertEqual(queued["command_type"], "vm_start")
        self.assertEqual(queued["payload"], {"vm_name": "vm1"})
        self.assertEqual(queued["target_host_id"], "remote")
        self.assertEqual(client.shutdown_remote_vm("remote", "vm1")["command_type"], "vm_shutdown")
        self.assertEqual(client.force_off_remote_vm("remote", "vm1")["command_type"], "vm_force_off")
        # The generic helper validates inputs before touching the Hub.
        with self.assertRaises(HyperGeryError):
            client.queue_vm_power_command("remote", "vm1", "delete")
        with self.assertRaises(HyperGeryError):
            client.queue_vm_power_command("remote", "  ", "start")
        with self.assertRaises(HyperGeryError):
            client.queue_vm_power_command("", "vm1", "start")
        # Hub-side allowlist still rejects destructive command types.
        for command_type in ("vm_delete", "vm_undefine", "delete_disks", "vm_reboot"):
            with self.assertRaises(HyperGeryError):
                client.create_command("remote", command_type, {"vm_name": "vm1"})


class PackageStagingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.staging = Path(self.tmp.name) / "staging"
        store = RegistryStore(Path(self.tmp.name) / "registry.sqlite3")
        self.server = RegistryServer(("127.0.0.1", 0), store, staging_dir=self.staging, auth_token="hgtest-token")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.base_url = f"http://{host}:{port}"
        from hypergery_ubuntu.registry import RegistryClient

        self.client = RegistryClient(self.base_url, token="hgtest-token")

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.tmp.cleanup()

    def make_package(self) -> Path:
        package = Path(self.tmp.name) / "out" / "mig-test"
        (package / "disks").mkdir(parents=True)
        (package / "manifest.json").write_text('{"migration_id": "mig-test"}', encoding="utf-8")
        (package / "disks" / "vm.qcow2").write_bytes(b"\x00" * 4096)
        return package

    def test_upload_list_download_delete_roundtrip(self):
        package = self.make_package()
        uploaded = self.client.upload_package("mig-test", package)
        self.assertEqual(len(uploaded["files"]), 2)
        self.assertTrue((self.staging / "mig-test" / "disks" / "vm.qcow2").is_file())

        files = self.client.list_package_files("mig-test")
        self.assertEqual({f["path"] for f in files}, {"manifest.json", "disks/vm.qcow2"})

        dest = Path(self.tmp.name) / "downloaded"
        self.client.download_package("mig-test", dest)
        self.assertEqual((dest / "manifest.json").read_text(encoding="utf-8"), '{"migration_id": "mig-test"}')
        self.assertEqual((dest / "disks" / "vm.qcow2").stat().st_size, 4096)

        deleted = self.client.delete_package("mig-test")
        self.assertTrue(deleted["deleted"])
        self.assertFalse((self.staging / "mig-test").exists())
        with self.assertRaises(HyperGeryError):
            self.client.list_package_files("mig-test")

    def test_download_missing_package_fails(self):
        with self.assertRaises(HyperGeryError):
            self.client.download_package("nope", Path(self.tmp.name) / "x")

    def test_delete_missing_package_is_safe(self):
        deleted = self.client.delete_package("nope")
        self.assertFalse(deleted["deleted"])

    def test_packages_listing_and_cleanup_endpoints(self):
        package = self.make_package()
        self.client.upload_package("mig-test", package)

        listing = self.client.list_staged_packages()
        self.assertEqual(listing["count"], 1)
        self.assertEqual(listing["packages"][0]["migration_id"], "mig-test")
        self.assertTrue(listing["packages"][0]["orphan"])
        self.assertEqual(listing["packages"][0]["file_count"], 2)
        self.assertGreater(listing["total_size_bytes"], 4096)

        # Default cleanup is a dry run and never touches recent packages.
        result = self.client.cleanup_staging(older_than_hours=24)
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["candidates"], [])
        self.assertEqual([item["migration_id"] for item in result["skipped"]], ["mig-test"])
        self.assertTrue((self.staging / "mig-test").is_dir())

        # Age the package, then a real cleanup removes it as an orphan.
        old = time.time() - 48 * 3600
        for item in [self.staging / "mig-test", *(self.staging / "mig-test").rglob("*")]:
            os.utime(item, (old, old))
        confirmed = self.client.cleanup_staging(older_than_hours=24, dry_run=False)
        self.assertFalse(confirmed["dry_run"])
        self.assertEqual(confirmed["deleted_count"], 1)
        self.assertEqual(confirmed["errors"], [])
        self.assertFalse((self.staging / "mig-test").exists())

    def test_cleanup_endpoint_rejects_invalid_threshold(self):
        from hypergery_ubuntu.registry import RegistryClient

        with self.assertRaises(HyperGeryError):
            RegistryClient(self.base_url, token="hgtest-token").cleanup_staging(older_than_hours="not-a-number")

    def test_path_traversal_is_rejected(self):
        secret = Path(self.tmp.name) / "secret.txt"
        secret.write_text("nope", encoding="utf-8")
        with self.assertRaises(HyperGeryError):
            self.client.upload_package_file("mig-test", "../escape.txt", secret)
        req = Request(self.base_url + "/packages/..%2F..%2Fetc/passwd", method="GET")
        req.add_header("Authorization", "Bearer hgtest-token")
        try:
            with urlopen(req, timeout=5) as response:
                status = response.status
        except Exception:
            status = 400
        self.assertNotEqual(status, 200)
        self.assertFalse((self.staging.parent / "escape.txt").exists())


class StagingCleanupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.staging = Path(self.tmp.name) / "staging"
        self.staging.mkdir()
        self.store = RegistryStore(Path(self.tmp.name) / "registry.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def make_staged_package(self, migration_id: str, *, age_hours: float = 48.0, size_bytes: int = 2048) -> Path:
        package = self.staging / migration_id
        (package / "disks").mkdir(parents=True)
        (package / "manifest.json").write_text(json.dumps({"migration_id": migration_id}), encoding="utf-8")
        (package / "disks" / "vm.qcow2").write_bytes(b"\x00" * size_bytes)
        stamp = time.time() - age_hours * 3600
        for item in [package, package / "disks", package / "manifest.json", package / "disks" / "vm.qcow2"]:
            os.utime(item, (stamp, stamp))
        return package

    def record_migration(self, migration_id: str, status: str) -> None:
        self.store.update_migration_status(
            migration_id,
            {
                "source_host_id": "source",
                "target_host_id": "target",
                "source_vm_name": "hg-source",
                "target_vm_name": "hg-target",
                "strategy": "hub_transfer",
                "status": status,
            },
        )

    def test_list_reports_sizes_orphans_and_migration_status(self):
        self.make_staged_package("mig-orphan", size_bytes=4096)
        self.make_staged_package("mig-done", size_bytes=1024)
        self.record_migration("mig-done", "done")
        listing = list_staged_packages(self.staging, self.store)
        self.assertEqual(listing["count"], 2)
        self.assertEqual(listing["orphan_count"], 1)
        by_id = {package["migration_id"]: package for package in listing["packages"]}
        self.assertTrue(by_id["mig-orphan"]["orphan"])
        self.assertEqual(by_id["mig-orphan"]["migration_status"], "")
        self.assertFalse(by_id["mig-done"]["orphan"])
        self.assertEqual(by_id["mig-done"]["migration_status"], "done")
        self.assertGreaterEqual(by_id["mig-orphan"]["size_bytes"], 4096)
        self.assertEqual(by_id["mig-orphan"]["file_count"], 2)
        self.assertGreater(by_id["mig-orphan"]["age_hours"], 24)

    def test_list_with_missing_staging_dir_is_empty(self):
        listing = list_staged_packages(self.staging / "missing", self.store)
        self.assertEqual(listing["count"], 0)
        self.assertEqual(listing["packages"], [])

    def test_dry_run_reports_candidates_but_deletes_nothing(self):
        package = self.make_staged_package("mig-orphan")
        result = cleanup_staged_packages(self.staging, self.store, older_than_hours=24, dry_run=True)
        self.assertTrue(result["dry_run"])
        self.assertEqual([item["migration_id"] for item in result["candidates"]], ["mig-orphan"])
        self.assertEqual(result["deleted_count"], 0)
        self.assertTrue(package.is_dir())

    def test_confirmed_cleanup_deletes_only_staging_packages(self):
        self.make_staged_package("mig-orphan")
        outside = Path(self.tmp.name) / "not-staging.txt"
        outside.write_text("untouchable", encoding="utf-8")
        result = cleanup_staged_packages(self.staging, self.store, older_than_hours=24, dry_run=False)
        self.assertEqual(result["deleted_count"], 1)
        self.assertEqual(result["errors"], [])
        self.assertFalse((self.staging / "mig-orphan").exists())
        self.assertTrue(outside.exists())
        self.assertTrue(self.staging.is_dir())

    def test_recent_package_is_never_deleted(self):
        self.make_staged_package("mig-fresh", age_hours=0.1)
        result = cleanup_staged_packages(self.staging, self.store, older_than_hours=24, dry_run=False)
        self.assertEqual(result["candidates"], [])
        self.assertIn("too recent", result["skipped"][0]["reason"])
        self.assertTrue((self.staging / "mig-fresh").is_dir())

    def test_minimum_age_floor_protects_against_zero_threshold(self):
        self.make_staged_package("mig-fresh", age_hours=0.1)
        result = cleanup_staged_packages(self.staging, self.store, older_than_hours=0, dry_run=False)
        self.assertEqual(result["older_than_hours"], 1.0)
        self.assertEqual(result["candidates"], [])
        self.assertTrue((self.staging / "mig-fresh").is_dir())

    def test_active_migration_package_is_always_skipped(self):
        for status in ("created", "uploaded", "waiting_target", "importing", "defining_vm"):
            migration_id = f"mig-{status.replace('_', '-')}"
            self.make_staged_package(migration_id)
            self.record_migration(migration_id, status)
        result = cleanup_staged_packages(self.staging, self.store, older_than_hours=1, dry_run=False)
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["deleted_count"], 0)
        for item in result["skipped"]:
            self.assertIn("migration is active", item["reason"])

    def test_failed_migration_requires_include_failed(self):
        self.make_staged_package("mig-failed")
        self.record_migration("mig-failed", "failed")
        kept = cleanup_staged_packages(self.staging, self.store, older_than_hours=24, dry_run=False)
        self.assertEqual(kept["candidates"], [])
        self.assertTrue((self.staging / "mig-failed").is_dir())
        removed = cleanup_staged_packages(
            self.staging, self.store, older_than_hours=24, dry_run=False, include_failed=True
        )
        self.assertEqual(removed["deleted_count"], 1)
        self.assertFalse((self.staging / "mig-failed").exists())

    def test_orphans_can_be_excluded(self):
        self.make_staged_package("mig-orphan")
        result = cleanup_staged_packages(
            self.staging, self.store, older_than_hours=24, dry_run=False, include_orphans=False
        )
        self.assertEqual(result["candidates"], [])
        self.assertIn("include_orphans disabled", result["skipped"][0]["reason"])
        self.assertTrue((self.staging / "mig-orphan").is_dir())

    def test_done_migration_leftover_is_candidate(self):
        self.make_staged_package("mig-done")
        self.record_migration("mig-done", "done")
        result = cleanup_staged_packages(self.staging, self.store, older_than_hours=24, dry_run=True)
        self.assertEqual(result["candidates"][0]["migration_id"], "mig-done")
        self.assertIn("leftover", result["candidates"][0]["reason"])

    def test_symlinked_entries_are_ignored(self):
        target = Path(self.tmp.name) / "real-data"
        (target / "disks").mkdir(parents=True)
        (target / "disks" / "vm.qcow2").write_bytes(b"\x00" * 1024)
        link = self.staging / "mig-link"
        link.symlink_to(target)
        listing = list_staged_packages(self.staging, self.store)
        self.assertEqual(listing["count"], 0)
        result = cleanup_staged_packages(self.staging, self.store, older_than_hours=1, dry_run=False)
        self.assertEqual(result["deleted_count"], 0)
        self.assertTrue(target.is_dir())

    def test_invalid_threshold_is_rejected(self):
        with self.assertRaises(HyperGeryError):
            cleanup_staged_packages(self.staging, self.store, older_than_hours="soon")
        with self.assertRaises(HyperGeryError):
            cleanup_staged_packages(self.staging, self.store, older_than_hours=-1)


if __name__ == "__main__":
    unittest.main()
