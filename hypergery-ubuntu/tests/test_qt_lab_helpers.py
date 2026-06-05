import unittest

from hypergery_ubuntu.backend import HyperGeryError, VmSummary
from hypergery_ubuntu.ui_qt.lab_helpers import (
    build_lab_preview,
    build_lab_topology,
    filter_vms_for_lab,
    lab_status_summary,
    order_lab_vms_for_action,
    plan_lab_power_action,
    topology_to_json,
    unify_lab_vms,
    vm_count_for_lab,
)


class QtLabHelperTests(unittest.TestCase):
    def test_build_lab_preview_generates_network_fields(self):
        preview = build_lab_preview("ASR Lab", "nat", existing_lab_ids=set(), existing_subnets=set())

        self.assertTrue(preview["valid"])
        self.assertEqual(preview["lab_id"], "asr-lab")
        self.assertEqual(preview["network_id"], "hg-net-asr-lab")
        self.assertTrue(preview["bridge_name"].startswith("hgbr"))
        self.assertRegex(preview["subnet"], r"^192\.168\.\d+\.0/24$")

    def test_build_lab_preview_rejects_existing_lab_id(self):
        preview = build_lab_preview("ASR Lab", "isolated", existing_lab_ids={"asr-lab"}, existing_subnets=set())

        self.assertFalse(preview["valid"])
        self.assertIn("already exists", preview["error"])

    def test_filter_vms_for_selected_lab(self):
        vms = [
            VmSummary(name="alpha", state="shut off", lab_id="asr-lab"),
            VmSummary(name="beta", state="running", lab_id="par-lab"),
        ]

        filtered = filter_vms_for_lab(vms, "asr-lab", selected_lab_only=True)

        self.assertEqual([vm.name for vm in filtered], ["alpha"])
        self.assertEqual(len(filter_vms_for_lab(vms, "asr-lab", selected_lab_only=False)), 2)

    def test_vm_count_uses_manifest_and_live_vms(self):
        lab = {"lab_id": "asr-lab", "vms": ["alpha", "missing"]}
        vms = [
            VmSummary(name="alpha", state="shut off", lab_id="asr-lab"),
            VmSummary(name="beta", state="running", lab_id="asr-lab"),
            VmSummary(name="other", state="running", lab_id="par-lab"),
        ]

        self.assertEqual(vm_count_for_lab(lab, vms), 3)


class LabTopologyTests(unittest.TestCase):
    def _lab(self, lab_id="asr-lab", **kwargs):
        base = {
            "lab_id": lab_id,
            "name": "ASR Lab",
            "network_mode": "isolated",
            "network_id": f"hg-net-{lab_id}-isolated",
            "subnet": "192.168.30.0/24",
            "bridge_name": "hgbr1234567",
            "vms": [],
        }
        base.update(kwargs)
        return base

    def test_topology_empty_lab(self):
        topo = build_lab_topology(self._lab(), [])
        self.assertEqual(topo["lab_id"], "asr-lab")
        self.assertEqual(topo["vms"], [])
        self.assertEqual(topo["network_mode"], "isolated")

    def test_topology_includes_live_vms(self):
        vms = [VmSummary(name="server", state="running", lab_id="asr-lab", ram_mib=4096, vcpus=2)]
        topo = build_lab_topology(self._lab(), vms)
        self.assertEqual(len(topo["vms"]), 1)
        node = topo["vms"][0]
        self.assertEqual(node["name"], "server")
        self.assertEqual(node["state"], "running")
        self.assertEqual(node["ram_mib"], 4096)
        self.assertTrue(node["live"])

    def test_topology_marks_manifest_only_vms_as_not_created(self):
        lab = self._lab(vms=["server", "ghost"])
        vms = [VmSummary(name="server", state="shut off", lab_id="asr-lab")]
        topo = build_lab_topology(lab, vms)
        names = {n["name"]: n for n in topo["vms"]}
        self.assertTrue(names["server"]["live"])
        self.assertFalse(names["ghost"]["live"])
        self.assertEqual(names["ghost"]["state"], "not created")

    def test_topology_excludes_vms_from_other_labs(self):
        vms = [
            VmSummary(name="server", state="running", lab_id="asr-lab"),
            VmSummary(name="other", state="running", lab_id="par-lab"),
        ]
        topo = build_lab_topology(self._lab(), vms)
        self.assertEqual(len(topo["vms"]), 1)
        self.assertEqual(topo["vms"][0]["name"], "server")

    def test_topology_deduplicates_manifest_and_live(self):
        lab = self._lab(vms=["server"])
        vms = [VmSummary(name="server", state="running", lab_id="asr-lab")]
        topo = build_lab_topology(lab, vms)
        self.assertEqual(len(topo["vms"]), 1)

    def test_topology_to_json_is_serialisable(self):
        import json
        vms = [VmSummary(name="srv", state="running", lab_id="asr-lab", ram_mib=2048, vcpus=1)]
        topo = build_lab_topology(self._lab(), vms)
        data = topology_to_json(topo)
        dumped = json.dumps(data)
        loaded = json.loads(dumped)
        self.assertEqual(loaded["lab_id"], "asr-lab")
        self.assertEqual(len(loaded["vms"]), 1)


class LabWorkspaceHelperTests(unittest.TestCase):
    LAB = {
        "lab_id": "asr-lab",
        "name": "ASR Lab",
        "vms": ["alpha", "ghost"],
        "vm_roles": {"alpha": "server", "remote-db": "db"},
    }
    LOCAL_VMS = [
        VmSummary(name="alpha", state="shut off", lab_id="asr-lab", ram_mib=2048, vcpus=2),
        VmSummary(name="other", state="running", lab_id="par-lab"),
    ]
    REMOTE_VMS = [
        {"host_id": "lenovo", "vm_name": "remote-db", "state": "running", "lab_id": "asr-lab", "ram_mib": 4096, "vcpus": 4},
        {"host_id": "lenovo", "vm_name": "remote-other", "state": "running", "lab_id": "par-lab"},
        # The local host's own inventory must be skipped (duplicates local VMs).
        {"host_id": "local-host", "vm_name": "alpha", "state": "shut off", "lab_id": "asr-lab"},
    ]

    def unified(self):
        return unify_lab_vms(self.LAB, self.LOCAL_VMS, self.REMOTE_VMS, "local-host")

    def test_unify_combines_local_remote_and_manifest_vms(self):
        unified = self.unified()
        by_name = {vm["name"]: vm for vm in unified}
        self.assertEqual(set(by_name), {"alpha", "ghost", "remote-db"})
        self.assertFalse(by_name["alpha"]["remote"])
        self.assertEqual(by_name["alpha"]["host_id"], "local-host")
        self.assertEqual(by_name["alpha"]["role"], "server")
        self.assertTrue(by_name["remote-db"]["remote"])
        self.assertEqual(by_name["remote-db"]["host_id"], "lenovo")
        self.assertEqual(by_name["remote-db"]["role"], "db")
        self.assertEqual(by_name["ghost"]["state"], "not created")

    def test_unify_normalizes_shutoff_state(self):
        unified = unify_lab_vms(
            {"lab_id": "asr-lab", "vms": []},
            [],
            [{"host_id": "lenovo", "vm_name": "vm1", "state": "shutoff", "lab_id": "asr-lab"}],
            "local-host",
        )
        self.assertEqual(unified[0]["state"], "shut off")

    def test_status_summary_counts_and_host_distribution(self):
        summary = lab_status_summary(self.unified())
        self.assertEqual(summary["counts"]["total"], 3)
        self.assertEqual(summary["counts"]["running"], 1)
        self.assertEqual(summary["counts"]["shut_off"], 1)
        self.assertEqual(summary["counts"]["not_created"], 1)
        self.assertEqual(summary["hosts"], {"local-host": ["alpha"], "lenovo": ["remote-db"]})

    def test_plan_start_targets_only_shut_off_vms(self):
        plan = plan_lab_power_action(self.unified(), "start")
        self.assertEqual([vm["name"] for vm in plan["targets"]], ["alpha"])
        self.assertEqual(plan["host_count"], 1)
        skipped_names = {item["name"] for item in plan["skipped"]}
        self.assertEqual(skipped_names, {"ghost", "remote-db"})

    def test_plan_shutdown_targets_only_running_vms(self):
        plan = plan_lab_power_action(self.unified(), "shutdown")
        self.assertEqual([vm["name"] for vm in plan["targets"]], ["remote-db"])
        self.assertTrue(plan["targets"][0]["remote"])

    def test_plan_rejects_unknown_actions(self):
        for action in ("force_off", "delete", "destroy"):
            with self.assertRaises(HyperGeryError):
                plan_lab_power_action(self.unified(), action)

    @staticmethod
    def _role_vm(name, role, state="shut off"):
        return {"name": name, "state": state, "host_id": "h", "ram_mib": 0, "vcpus": 0, "remote": False, "role": role}

    def role_fleet(self, state):
        return [
            self._role_vm("zz-client", "client", state),
            self._role_vm("a-noro", "", state),
            self._role_vm("web1", "web", state),
            self._role_vm("dc1", "ad", state),
            self._role_vm("edge", "router", state),
            self._role_vm("fw", "firewall", state),
            self._role_vm("db1", "db", state),
            self._role_vm("dns1", "dns", state),
        ]

    def test_start_order_boots_infrastructure_first(self):
        plan = plan_lab_power_action(self.role_fleet("shut off"), "start")
        names = [vm["name"] for vm in plan["targets"]]
        self.assertEqual(names, ["edge", "fw", "dc1", "dns1", "db1", "web1", "zz-client", "a-noro"])

    def test_shutdown_order_stops_clients_first(self):
        plan = plan_lab_power_action(self.role_fleet("running"), "shutdown")
        names = [vm["name"] for vm in plan["targets"]]
        self.assertEqual(names, ["a-noro", "zz-client", "db1", "web1", "dc1", "dns1", "edge", "fw"])

    def test_order_without_roles_is_alphabetical(self):
        vms = [self._role_vm(name, "") for name in ("charlie", "alpha", "bravo")]
        ordered = order_lab_vms_for_action(vms, "start")
        self.assertEqual([vm["name"] for vm in ordered], ["alpha", "bravo", "charlie"])
        ordered = order_lab_vms_for_action(vms, "shutdown")
        self.assertEqual([vm["name"] for vm in ordered], ["alpha", "bravo", "charlie"])


if __name__ == "__main__":
    unittest.main()
