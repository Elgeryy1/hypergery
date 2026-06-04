import unittest

from hypergery_ubuntu.backend import VmSummary
from hypergery_ubuntu.ui_qt.lab_helpers import build_lab_preview, build_lab_topology, filter_vms_for_lab, topology_to_json, vm_count_for_lab


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


if __name__ == "__main__":
    unittest.main()
