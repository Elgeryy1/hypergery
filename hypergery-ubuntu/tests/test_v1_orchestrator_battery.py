import tempfile
import unittest
from pathlib import Path

from hypergery_ubuntu.v1.battery import BatteryService, BatteryState
from hypergery_ubuntu.v1.errors import BatteryUnavailableError, OrchestratorError
from hypergery_ubuntu.v1.hosts import HostInfo
from hypergery_ubuntu.v1.orchestrator import OrchestratorService, classify_vm_weight
from hypergery_ubuntu.v1.providers import VmInfo
from hypergery_ubuntu.v1.settings import V1Settings


def fake_battery_dir(tmp: Path, percent: int, status: str = "Discharging") -> Path:
    battery = tmp / "BAT0"
    battery.mkdir(parents=True)
    (battery / "capacity").write_text(f"{percent}\n", encoding="utf-8")
    (battery / "status").write_text(f"{status}\n", encoding="utf-8")
    return tmp


def battery_state(percent: int | None, *, tier: str | None = None, charging: bool = False) -> BatteryState:
    service = BatteryService(settings=V1Settings())
    computed_tier = tier or service.tier_for(percent, charging=charging)
    return BatteryState(available=percent is not None, percent=percent, charging=charging, tier=computed_tier, status="discharging" if not charging else "charging")


class BatteryServiceTests(unittest.TestCase):
    def make_service(self, tmp: Path, percent: int, status: str = "Discharging", **settings_kwargs) -> BatteryService:
        return BatteryService(settings=V1Settings(**settings_kwargs), power_supply_dir=str(fake_battery_dir(tmp, percent, status)))

    def test_read_real_sysfs_layout_and_tiers(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.make_service(Path(tmp), 45)
            state = service.read()
        self.assertTrue(state.available)
        self.assertEqual(state.percent, 45)
        self.assertEqual(state.tier, "eco")
        self.assertEqual(state.thresholds["offload"], 30)

    def test_tier_boundaries(self):
        service = BatteryService(settings=V1Settings())
        for percent, tier in ((100, "normal"), (51, "normal"), (50, "eco"), (30, "offload"), (20, "emergency"), (10, "critical"), (1, "critical")):
            self.assertEqual(service.tier_for(percent), tier, percent)
        self.assertEqual(service.tier_for(5, charging=True), "normal")
        self.assertEqual(service.tier_for(None), "normal")

    def test_require_raises_without_battery(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "none"
            empty.mkdir()
            service = BatteryService(settings=V1Settings(), power_supply_dir=str(empty))
            state = service.read()
            if state.available:  # psutil may report the dev laptop battery
                self.skipTest("psutil reports a real battery on this machine")
            with self.assertRaises(BatteryUnavailableError):
                service.require()

    def test_events_only_on_tier_transitions(self):
        service = BatteryService(settings=V1Settings())
        previous = battery_state(60)
        worse = battery_state(25)
        events = service.events(previous, worse)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["tier"], "offload")
        self.assertEqual(events[0]["direction"], "worsened")
        self.assertEqual(service.events(worse, battery_state(25)), [])
        improved = service.events(worse, battery_state(80))
        self.assertEqual(improved[0]["direction"], "improved")

    def test_recommend_only_mode_returns_unprepared_actions(self):
        service = BatteryService(settings=V1Settings(battery_mode="recommend_only"))
        actions = service.recommended_actions(battery_state(25))
        kinds = {action["kind"] for action in actions}
        self.assertIn("recommend_stop_heavy_vms", kinds)
        self.assertIn("prepare_teleport", kinds)
        self.assertTrue(all(not action["prepared"] and not action["execute"] for action in actions))

    def test_emergency_adds_nas_commit_and_critical_adds_shutdown(self):
        service = BatteryService(settings=V1Settings(battery_mode="auto_prepare"))
        emergency = {a["kind"] for a in service.recommended_actions(battery_state(15))}
        self.assertIn("nas_commit", emergency)
        critical = {a["kind"] for a in service.recommended_actions(battery_state(5))}
        self.assertIn("emergency_shutdown_recommended", critical)
        self.assertTrue(all(a["prepared"] for a in service.recommended_actions(battery_state(15))))

    def test_auto_execute_safe_only_executes_safe_actions(self):
        service = BatteryService(settings=V1Settings(battery_mode="auto_execute_safe"))
        actions = service.recommended_actions(battery_state(15))
        by_kind = {action["kind"]: action for action in actions}
        self.assertTrue(by_kind["reduce_refresh"]["execute"])
        self.assertFalse(by_kind["prepare_teleport"]["execute"])
        self.assertFalse(by_kind["nas_commit"]["execute"])

    def test_disabled_mode_and_charging_return_nothing(self):
        disabled = BatteryService(settings=V1Settings(battery_mode="disabled"))
        self.assertEqual(disabled.recommended_actions(battery_state(5)), [])
        service = BatteryService(settings=V1Settings())
        self.assertEqual(service.recommended_actions(battery_state(5, charging=True)), [])


def host(host_id, *, role="unknown", status="online", ram_total=16384, ram_free=12000, caps=("can_run_vms",)):
    return HostInfo(
        id=host_id,
        role=role,
        status=status,
        ram_total_mib=ram_total,
        ram_free_mib=ram_free,
        capabilities=list(caps),
    )


def vm(vm_id, *, ram_mb=2048, status="running", host_id="laptop", lab_id="asr-lab", notes=""):
    return VmInfo(id=vm_id, ram_mb=ram_mb, status=status, host_id=host_id, lab_id=lab_id, notes=notes)


class VmWeightTests(unittest.TestCase):
    def test_weight_classification(self):
        self.assertEqual(classify_vm_weight(vm("a", ram_mb=1024)), "light")
        self.assertEqual(classify_vm_weight(vm("b", ram_mb=4096)), "medium")
        self.assertEqual(classify_vm_weight(vm("c", ram_mb=8192)), "heavy")
        self.assertEqual(classify_vm_weight(vm("d", ram_mb=8192, notes="critical db")), "critical")


class OrchestratorTests(unittest.TestCase):
    def make_orchestrator(self, **settings_kwargs) -> OrchestratorService:
        return OrchestratorService(settings=V1Settings(**settings_kwargs))

    def plan_one(self, plans, vm_id):
        for plan in plans:
            if plan.vm_id == vm_id:
                return plan
        raise AssertionError(f"No plan for {vm_id}")

    def test_low_battery_moves_heavy_vm_to_home_pc_with_explanation(self):
        hosts = [host("laptop", role="laptop", ram_free=3200), host("home-pc", role="home_pc", ram_free=21000)]
        plans = self.make_orchestrator().plan(
            hosts=hosts,
            vms=[vm("winserver", ram_mb=6144)],
            battery=battery_state(28),
            local_host_id="laptop",
        )
        plan = self.plan_one(plans, "winserver")
        self.assertEqual(plan.target_host, "home-pc")
        self.assertTrue(plan.is_move)
        self.assertIn("28%", plan.reason)
        self.assertIn("offload", plan.reason)
        self.assertIn("21000 MiB free", plan.reason)
        self.assertIn("fallback", plan.reason)
        self.assertEqual(plan.actions[0]["kind"], "teleport")
        self.assertEqual(plan.actions[0]["mode"], "dry_run")
        self.assertGreaterEqual(plan.confidence, 0.8)

    def test_ram_pressure_avoids_full_host(self):
        hosts = [
            host("laptop", role="laptop", ram_free=12000),
            host("home-pc", role="home_pc", ram_free=2048),  # not enough headroom for heavy
        ]
        plans = self.make_orchestrator().plan(
            hosts=hosts, vms=[vm("bigdb", ram_mb=8192, host_id="laptop")], battery=battery_state(90), local_host_id="laptop"
        )
        plan = self.plan_one(plans, "bigdb")
        # home-pc lacks headroom (2048 - 8192 < threshold) → stays local.
        self.assertEqual(plan.target_host, "laptop")

    def test_offline_host_is_never_a_target(self):
        hosts = [host("laptop", role="laptop"), host("home-pc", role="home_pc", status="offline", ram_free=32000)]
        plans = self.make_orchestrator().plan(
            hosts=hosts, vms=[vm("heavy1", ram_mb=8192)], battery=battery_state(25), local_host_id="laptop"
        )
        plan = self.plan_one(plans, "heavy1")
        self.assertNotEqual(plan.target_host, "home-pc")

    def test_light_vm_prefers_local(self):
        hosts = [host("laptop", role="laptop"), host("home-pc", role="home_pc", ram_free=32000)]
        plans = self.make_orchestrator().plan(hosts=hosts, vms=[vm("tiny", ram_mb=1024)], battery=battery_state(90), local_host_id="laptop")
        plan = self.plan_one(plans, "tiny")
        self.assertEqual(plan.target_host, "laptop")
        self.assertIn("light", plan.reason)

    def test_heavy_vm_prefers_home_pc_when_battery_is_fine(self):
        hosts = [host("laptop", role="laptop", ram_free=12000), host("home-pc", role="home_pc", ram_free=24000)]
        plans = self.make_orchestrator().plan(hosts=hosts, vms=[vm("heavy1", ram_mb=8192)], battery=battery_state(95), local_host_id="laptop")
        plan = self.plan_one(plans, "heavy1")
        self.assertEqual(plan.target_host, "home-pc")
        self.assertIn("home_pc", plan.reason)

    def test_critical_vm_never_moves_and_warns(self):
        hosts = [host("laptop", role="laptop"), host("home-pc", role="home_pc", ram_free=32000)]
        plans = self.make_orchestrator().plan(
            hosts=hosts, vms=[vm("payments", ram_mb=8192, notes="critical")], battery=battery_state(5), local_host_id="laptop"
        )
        plan = self.plan_one(plans, "payments")
        self.assertFalse(plan.is_move)
        self.assertTrue(plan.warnings)
        self.assertEqual(plan.actions[0]["kind"], "stay")

    def test_offline_mode_keeps_everything_local(self):
        hosts = [host("laptop", role="laptop"), host("home-pc", role="home_pc", ram_free=32000)]
        plans = self.make_orchestrator(offline_mode=True).plan(
            hosts=hosts, vms=[vm("heavy1", ram_mb=8192)], battery=battery_state(15), local_host_id="laptop"
        )
        plan = self.plan_one(plans, "heavy1")
        self.assertEqual(plan.target_host, "laptop")
        self.assertIn("Offline mode", plan.reason)

    def test_guest_without_remote_permission_stays_local_with_warning(self):
        hosts = [host("laptop", role="laptop"), host("home-pc", role="home_pc", ram_free=32000)]
        plans = self.make_orchestrator().plan(
            hosts=hosts, vms=[vm("guestvm", ram_mb=8192)], battery=battery_state(15), local_host_id="laptop", allow_remote=False
        )
        plan = self.plan_one(plans, "guestvm")
        self.assertEqual(plan.target_host, "laptop")
        self.assertTrue(any("denied" in warning for warning in plan.warnings))

    def test_lab_filter_and_empty_hosts(self):
        hosts = [host("laptop", role="laptop")]
        plans = self.make_orchestrator().plan(
            hosts=hosts,
            vms=[vm("a", lab_id="asr-lab"), vm("b", lab_id="db-lab")],
            battery=None,
            local_host_id="laptop",
            lab_id="db-lab",
        )
        self.assertEqual([plan.vm_id for plan in plans], ["b"])
        with self.assertRaises(OrchestratorError):
            self.make_orchestrator().plan(hosts=[], vms=[vm("a")])


if __name__ == "__main__":
    unittest.main()
