"""v1.5 live migration: preflight, flags, progreso, rollback e invariantes."""

from __future__ import annotations

import unittest

from hypergery_ubuntu.backend import CommandResult
from hypergery_ubuntu.v1.errors import HyperGeryError
from hypergery_ubuntu.v1.live_migration import (
    LiveMigrationPlan,
    LiveMigrator,
    estimate_downtime_ms,
    parse_domjobinfo,
    target_uri_host,
)
from hypergery_ubuntu.v1.progress import ProgressChannel

TARGET = "qemu+ssh://gery@portatil/system"

DOMAIN_XML = """<domain type='kvm'>
  <name>web01</name>
  <cpu mode='host-model'/>
  <devices>
    <disk type='file' device='disk'><source file='/var/lib/libvirt/images/web01.qcow2'/></disk>
    {extra}
  </devices>
</domain>
"""

JOBINFO_RUNNING = """Job type:         Unbounded
Operation:        Outgoing migration
Time elapsed:     5000         ms
Data processed:   1024.000 MiB
Data remaining:   512.000 MiB
Data total:       2048.000 MiB
Memory processed: 1024.000 MiB
Memory remaining: 512.000 MiB
Memory total:     2048.000 MiB
Memory bandwidth: 800.000 MiB/s
Dirty rate:       1000 pages/s
Iteration:        3
"""

JOBINFO_COMPLETED = """Job type:         Completed
Operation:        Outgoing migration
Time elapsed:     21000        ms
Total downtime:   42           ms
Memory total:     2048.000 MiB
"""


def _ok(stdout: str = "") -> CommandResult:
    return CommandResult(["virsh"], 0, stdout, "")


def _fail(stderr: str = "error") -> CommandResult:
    return CommandResult(["virsh"], 1, "", stderr)


class ScriptedHost:
    """Simula virsh local (source) y remoto (target) con un guion mutable."""

    def __init__(self):
        self.calls: list[list[str]] = []
        self.script: dict[tuple[str, ...], object] = {}
        self.defaults_ok = True

    def _dispatch(self, key_args: list[str]):
        self.calls.append(list(key_args))
        for length in range(len(key_args), 0, -1):
            entry = self.script.get(tuple(key_args[:length]))
            if entry is not None:
                return entry() if callable(entry) else entry
        return _ok() if self.defaults_ok else _fail()

    def virsh(self, args, *, check=True, timeout=120):
        result = self._dispatch(["S", *args])
        if check and result.returncode != 0:
            raise HyperGeryError(result.stderr)
        return result

    def run(self, cmd, *, check=True, timeout=120):
        if cmd[:2] == ["virsh", "--connect"]:
            # cmd = ["virsh", "--connect", URI, *args] → virsh del destino.
            result = self._dispatch(["T", *cmd[3:]])
        else:
            # Comandos locales/ssh de la preparación (qemu-img, ssh mkdir…).
            result = self._dispatch(["R", cmd[0]])
        if check and result.returncode != 0:
            raise HyperGeryError(result.stderr)
        return result


def _happy_host(*, extra_devices: str = "", migrate_result: CommandResult | None = None) -> ScriptedHost:
    host = ScriptedHost()
    host.script.update(
        {
            ("S", "domstate", "web01"): _ok("running\n"),
            ("S", "dumpxml", "web01"): _ok(DOMAIN_XML.format(extra=extra_devices)),
            ("S", "hostname"): _ok("pc-sobremesa\n"),
            ("S", "dominfo", "web01"): _ok("Max memory:     2097152 KiB\n"),
            ("S", "migrate"): migrate_result or _ok(),
            ("S", "domjobinfo", "web01", "--completed"): _ok(JOBINFO_COMPLETED),
            ("S", "domjobinfo", "web01"): _ok(JOBINFO_RUNNING),
            # Tras migrar, el origen queda apagado/definido.
            ("T", "version"): _ok("Compiled against library: libvirt 10.0.0\n"),
            ("T", "hostname"): _ok("portatil\n"),
            ("T", "dominfo", "web01"): _fail("Domain not found"),
            ("T", "nodememstats"): _ok("total  : 16000000 KiB\nfree   : 8000000 KiB\n"),
            ("T", "domstate", "web01"): _ok("running\n"),
            # Preparación del destino en block migration (qemu-img info -U + ssh mkdir/create).
            ("R", "qemu-img"): _ok('{"virtual-size": 1073741824}'),
            ("R", "ssh"): _ok(),
        }
    )
    # Después del switchover el origen ya no está running.
    states = iter(["running\n"] * 1 + ["shut off\n"] * 50)
    host.script[("S", "domstate", "web01")] = lambda: _ok(next(states, "shut off\n"))
    return host


class PlanValidationTests(unittest.TestCase):
    def test_insecure_uris_are_rejected(self):
        for uri in ("qemu+tcp://host/system", "http://host", "tcp://host", ""):
            with self.assertRaises(HyperGeryError, msg=uri):
                LiveMigrationPlan(vm_name="web01", target_uri=uri)

    def test_secure_uris_are_accepted(self):
        for uri in (TARGET, "qemu+tls://portatil/system"):
            self.assertEqual(LiveMigrationPlan(vm_name="web01", target_uri=uri).target_uri, uri)


class DomJobInfoParsingTests(unittest.TestCase):
    def test_running_jobinfo_parses_metrics(self):
        metrics = parse_domjobinfo(JOBINFO_RUNNING)
        self.assertEqual(metrics["data_total_mib"], 2048.0)
        self.assertEqual(metrics["data_processed_mib"], 1024.0)
        self.assertEqual(metrics["memory_bandwidth_mibps"], 800.0)
        self.assertEqual(metrics["iteration"], 3.0)
        self.assertEqual(metrics["time_elapsed_ms"], 5000.0)

    def test_completed_jobinfo_has_measured_downtime(self):
        metrics = parse_domjobinfo(JOBINFO_COMPLETED)
        self.assertEqual(metrics["total_downtime_ms"], 42.0)

    def test_downtime_estimate(self):
        self.assertIsNone(estimate_downtime_ms(2048, 64, 0))
        self.assertIsNone(estimate_downtime_ms(2048, 2000, 1000), "dirty rate >= ancho de banda: no converge")
        self.assertGreater(estimate_downtime_ms(2048, 64, 1024), 0)


class PreflightTests(unittest.TestCase):
    def _migrator(self, host, **plan_kwargs) -> LiveMigrator:
        plan = LiveMigrationPlan(vm_name="web01", target_uri=TARGET, **plan_kwargs)
        return LiveMigrator(host, plan, channel=ProgressChannel())

    def test_stopped_vm_is_rejected(self):
        host = _happy_host()
        host.script[("S", "domstate", "web01")] = _ok("shut off\n")
        result = self._migrator(host).run()
        self.assertFalse(result["ok"])
        self.assertIn("RUNNING", result["error"])

    def test_pci_passthrough_blocks_live_migration(self):
        host = _happy_host(
            extra_devices="<hostdev mode='subsystem' type='pci'><source/></hostdev>"
        )
        result = self._migrator(host).run()
        self.assertFalse(result["ok"])
        self.assertIn("passthrough", result["error"])

    def test_virgl_3d_acceleration_blocks_live_migration(self):
        host = _happy_host(
            extra_devices="<video><model type='virtio'><acceleration accel3d='yes'/></model></video>"
        )
        result = self._migrator(host).run()
        self.assertFalse(result["ok"])
        self.assertIn("3D acceleration", result["error"])

    def test_egl_headless_graphics_blocks_live_migration(self):
        host = _happy_host(extra_devices="<graphics type='egl-headless'><gl/></graphics>")
        result = self._migrator(host).run()
        self.assertFalse(result["ok"])
        self.assertIn("3D acceleration", result["error"])

    def test_unreachable_target_fails_preflight(self):
        host = _happy_host()
        host.script[("T", "version")] = _fail("ssh: connect refused")
        result = self._migrator(host).run()
        self.assertFalse(result["ok"])
        self.assertIn("Cannot reach target", result["error"])

    def test_same_host_is_rejected(self):
        host = _happy_host()
        host.script[("T", "hostname")] = _ok("pc-sobremesa\n")
        result = self._migrator(host).run()
        self.assertFalse(result["ok"])
        self.assertIn("same host", result["error"])

    def test_duplicate_name_on_target_is_rejected(self):
        host = _happy_host()
        host.script[("T", "dominfo", "web01")] = _ok("Name: web01\n")
        result = self._migrator(host).run()
        self.assertFalse(result["ok"])
        self.assertIn("already exists", result["error"])

    def test_insufficient_target_ram_is_rejected(self):
        host = _happy_host()
        host.script[("T", "nodememstats")] = _ok("free   : 102400 KiB\n")  # 100 MiB
        result = self._migrator(host).run()
        self.assertFalse(result["ok"])
        self.assertIn("free but the VM needs", result["error"])

    def test_preflight_never_touches_source_or_target(self):
        host = _happy_host()
        host.script[("T", "version")] = _fail("down")
        self._migrator(host).run()
        mutating = [c for c in host.calls if c[1] in {"migrate", "undefine", "destroy", "domjobabort"}]
        self.assertEqual(mutating, [])


class HappyPathTests(unittest.TestCase):
    def test_full_live_migration_flow(self):
        host = _happy_host()
        channel = ProgressChannel()
        plan = LiveMigrationPlan(vm_name="web01", target_uri=TARGET, shared_storage=True)
        migrator = LiveMigrator(host, plan, channel=channel)
        result = migrator.run()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["completed_phases"], ["preflight", "transfer", "switchover", "activate"])
        self.assertEqual(result["measured_downtime_ms"], 42.0)

        migrate_call = next(c for c in host.calls if c[1] == "migrate")
        self.assertIn("--live", migrate_call)
        self.assertIn("--persistent", migrate_call)
        self.assertIn("--abort-on-error", migrate_call)
        self.assertIn("--auto-converge", migrate_call)
        self.assertNotIn("--undefinesource", migrate_call, "el origen se limpia SOLO al confirmar (activate)")
        self.assertNotIn("--copy-storage-all", migrate_call, "shared storage: sin block migration")

        # El origen se undefine SOLO después de confirmar el destino.
        undefine_index = next(i for i, c in enumerate(host.calls) if c[:2] == ["S", "undefine"])
        target_confirm_index = next(i for i, c in enumerate(host.calls) if c[:3] == ["T", "domstate", "web01"])
        self.assertGreater(undefine_index, target_confirm_index)

        state = channel.get(result["operation_id"])
        self.assertEqual(state["status"], "done")
        self.assertEqual(state["percent"], 100.0)

    def test_migrate_pins_data_channel_to_target_host(self):
        # Regresión: sin --migrateuri, el NBD de la block migration usaba el
        # hostname que anuncia el destino y el origen no lo resolvía
        # ("address resolution failed for <hostname>").
        self.assertEqual(target_uri_host("qemu+ssh://gerard@192.168.1.44/system"), "192.168.1.44")
        self.assertEqual(target_uri_host("qemu+ssh://portatil:22/system"), "portatil")
        host = _happy_host()
        plan = LiveMigrationPlan(vm_name="web01", target_uri=TARGET, shared_storage=False)
        LiveMigrator(host, plan, channel=ProgressChannel()).run()
        migrate_call = next(c for c in host.calls if c[1] == "migrate")
        self.assertIn("--migrateuri", migrate_call)
        self.assertIn("tcp://portatil", migrate_call)

    def test_block_migration_flags(self):
        host = _happy_host()
        plan = LiveMigrationPlan(vm_name="web01", target_uri=TARGET, shared_storage=False)
        result = LiveMigrator(host, plan, channel=ProgressChannel()).run()
        self.assertTrue(result["ok"], result)
        migrate_call = next(c for c in host.calls if c[1] == "migrate")
        self.assertIn("--copy-storage-all", migrate_call)

    def test_incremental_block_migration_flag(self):
        host = _happy_host()
        plan = LiveMigrationPlan(
            vm_name="web01", target_uri=TARGET, shared_storage=False, incremental_storage=True
        )
        LiveMigrator(host, plan, channel=ProgressChannel()).run()
        migrate_call = next(c for c in host.calls if c[1] == "migrate")
        self.assertIn("--copy-storage-inc", migrate_call)
        self.assertNotIn("--copy-storage-all", migrate_call)

    def test_postcopy_flags(self):
        host = _happy_host()
        plan = LiveMigrationPlan(vm_name="web01", target_uri=TARGET, shared_storage=True, postcopy=True)
        LiveMigrator(host, plan, channel=ProgressChannel()).run()
        migrate_call = next(c for c in host.calls if c[1] == "migrate")
        self.assertIn("--postcopy", migrate_call)
        self.assertIn("--postcopy-after-precopy", migrate_call)

    def test_keep_source_definition(self):
        host = _happy_host()
        plan = LiveMigrationPlan(
            vm_name="web01", target_uri=TARGET, shared_storage=True, undefine_source_on_success=False
        )
        result = LiveMigrator(host, plan, channel=ProgressChannel()).run()
        self.assertTrue(result["ok"])
        self.assertEqual([c for c in host.calls if c[:2] == ["S", "undefine"]], [])


class FailureAndRollbackTests(unittest.TestCase):
    def test_failed_migrate_leaves_source_running_and_cleans_target(self):
        host = _happy_host(migrate_result=_fail("operation failed: migration job: unexpectedly failed"))
        # Origen sigue corriendo tras el fallo; el destino quedó a medias (paused).
        host.script[("S", "domstate", "web01")] = _ok("running\n")
        host.script[("T", "domstate", "web01")] = _ok("paused\n")
        plan = LiveMigrationPlan(vm_name="web01", target_uri=TARGET, shared_storage=True)
        result = LiveMigrator(host, plan, channel=ProgressChannel()).run()
        self.assertFalse(result["ok"])
        self.assertIn("virsh migrate failed", result["error"])
        self.assertIn(["S", "domjobabort", "web01"], host.calls)
        self.assertIn(["T", "destroy", "web01"], host.calls)
        self.assertIn(["T", "undefine", "web01", "--nvram"], host.calls)
        # El origen JAMÁS se undefine en un fallo.
        self.assertEqual([c for c in host.calls if c[:2] == ["S", "undefine"]], [])

    def test_rollback_never_destroys_a_promoted_target(self):
        # Si el destino quedó running y el origen ya no: no tocar el destino.
        host = _happy_host()
        plan = LiveMigrationPlan(vm_name="web01", target_uri=TARGET, shared_storage=True)
        migrator = LiveMigrator(host, plan, channel=ProgressChannel())
        host.script[("S", "domstate", "web01")] = _ok("shut off\n")
        host.script[("T", "domstate", "web01")] = _ok("running\n")
        migrator._rollback_migrate({"plan": plan})
        self.assertNotIn(["T", "destroy", "web01"], host.calls)
        self.assertNotIn(["T", "undefine", "web01", "--nvram"], host.calls)

    def test_activate_refuses_running_on_both_hosts(self):
        host = _happy_host()
        host.script[("S", "domstate", "web01")] = _ok("running\n")
        host.script[("T", "domstate", "web01")] = _ok("running\n")
        plan = LiveMigrationPlan(vm_name="web01", target_uri=TARGET, shared_storage=True)
        migrator = LiveMigrator(host, plan, channel=ProgressChannel())
        with self.assertRaises(HyperGeryError) as ctx:
            migrator._run_activate({"report": lambda *a, **k: None, "plan": plan})
        self.assertIn("BOTH hosts", str(ctx.exception))
        self.assertEqual([c for c in host.calls if c[:2] == ["S", "undefine"]], [])

    def test_activate_keeps_source_if_target_never_runs(self):
        host = _happy_host()
        host.script[("T", "domstate", "web01")] = _fail("Domain not found")
        plan = LiveMigrationPlan(vm_name="web01", target_uri=TARGET, shared_storage=True)
        migrator = LiveMigrator(host, plan, channel=ProgressChannel())
        import hypergery_ubuntu.v1.live_migration as lm

        original = lm.time.monotonic
        ticks = iter([0, 100, 200])
        lm.time.monotonic = lambda: next(ticks, 300)
        try:
            with self.assertRaises(HyperGeryError) as ctx:
                migrator._run_activate({"report": lambda *a, **k: None, "plan": plan})
        finally:
            lm.time.monotonic = original
        self.assertIn("source kept", str(ctx.exception))
        self.assertEqual([c for c in host.calls if c[:2] == ["S", "undefine"]], [])


if __name__ == "__main__":
    unittest.main()


class SharedStorageFilesystemGuardTests(unittest.TestCase):
    """U10 real (2026-06-10): el write-lock de QEMU no hace handoff fiable
    sobre SMB → CIFS/SMB queda NO soportado para shared-storage (NFS sí;
    block migration no se ve afectada)."""

    def _migrator(self, host, **plan_kwargs) -> LiveMigrator:
        plan = LiveMigrationPlan(vm_name="web01", target_uri=TARGET, **plan_kwargs)
        return LiveMigrator(host, plan, channel=ProgressChannel())

    def _run_with_fstype(self, fstype: str, **plan_kwargs):
        from unittest.mock import patch

        from hypergery_ubuntu.v1 import live_migration

        host = _happy_host()
        with patch.object(live_migration, "disk_filesystem_type", return_value=fstype):
            return self._migrator(host, **plan_kwargs).run(), host

    def test_cifs_shared_storage_is_rejected_with_human_error(self):
        for fstype in ("cifs", "smb3", "fuse.smb"):
            result, host = self._run_with_fstype(fstype, shared_storage=True)
            self.assertFalse(result["ok"], fstype)
            self.assertIn("CIFS/SMB no está soportado", result["error"])
            self.assertIn("NFS", result["error"])
            # El rechazo ocurre en preflight: nada mutante llegó a ejecutarse.
            mutating = [c for c in host.calls if c[1] in {"migrate", "undefine", "destroy"}]
            self.assertEqual(mutating, [])

    def test_block_migration_on_cifs_is_still_allowed(self):
        result, _host = self._run_with_fstype("cifs", shared_storage=False)
        self.assertTrue(result["ok"], result.get("error"))

    def test_nfs_and_local_filesystems_pass_the_guard(self):
        for fstype in ("nfs", "nfs4", "ext4", "btrfs", ""):
            result, _host = self._run_with_fstype(fstype, shared_storage=True)
            self.assertTrue(result["ok"], f"{fstype}: {result.get('error')}")


class DiskFilesystemTypeTests(unittest.TestCase):
    def test_longest_prefix_match_wins(self):
        import tempfile

        from hypergery_ubuntu.v1.live_migration import disk_filesystem_type

        with tempfile.NamedTemporaryFile("w", suffix=".mounts", delete=False) as handle:
            handle.write(
                "/dev/sda2 / ext4 rw 0 0\n"
                "//nas/share /mnt/hypergery-nas cifs rw 0 0\n"
                "nas:/vms /mnt/hypergery-nas/nfs nfs4 rw 0 0\n"
            )
            mounts = handle.name
        self.assertEqual(disk_filesystem_type("/home/x/vm.qcow2", mounts), "ext4")
        self.assertEqual(disk_filesystem_type("/mnt/hypergery-nas/vm.qcow2", mounts), "cifs")
        self.assertEqual(disk_filesystem_type("/mnt/hypergery-nas/nfs/vm.qcow2", mounts), "nfs4")
        # Prefijo de nombre parecido no cuenta como subruta.
        self.assertEqual(disk_filesystem_type("/mnt/hypergery-nas-otra/vm.qcow2", mounts), "ext4")

    def test_unreadable_mounts_returns_empty(self):
        from hypergery_ubuntu.v1.live_migration import disk_filesystem_type

        self.assertEqual(disk_filesystem_type("/x/y.qcow2", "/nonexistent-mounts"), "")
