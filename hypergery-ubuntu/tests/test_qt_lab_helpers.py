import unittest

from hypergery_ubuntu.backend import VmSummary
from hypergery_ubuntu.ui_qt.lab_helpers import build_lab_preview, filter_vms_for_lab, vm_count_for_lab


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


if __name__ == "__main__":
    unittest.main()
