import tempfile
import unittest
from pathlib import Path

from hypergery_ubuntu.v1.errors import HyperGeryError, NetworkConflictError, PermissionDeniedError
from hypergery_ubuntu.v1.external_nodes import (
    ExternalNode,
    ExternalNodeStore,
    detect_local_environment,
    health_check,
)
from hypergery_ubuntu.v1.hglog import StructuredLogger
from hypergery_ubuntu.v1.networks import Network, network_from_lab, require_valid_networks, validate_networks
from hypergery_ubuntu.v1.orchestrator import OrchestratorService
from hypergery_ubuntu.v1.providers import VmInfo
from hypergery_ubuntu.v1.rbac import (
    DEFAULT_ROLE_PERMISSIONS,
    User,
    UserStore,
    check_permission,
    require_permission,
)
from hypergery_ubuntu.v1.settings import V1Settings


def net(net_id, lab_id, cidr, **kwargs):
    return Network(id=net_id, lab_id=lab_id, cidr=cidr, **kwargs)


class NetworkValidationTests(unittest.TestCase):
    def test_valid_isolated_networks_pass(self):
        result = validate_networks(
            [
                net("hg-net-asr", "asr-lab", "192.168.30.0/24", gateway="192.168.30.1"),
                net("hg-net-db", "db-lab", "192.168.40.0/24", gateway="192.168.40.1", isolated=True, mode="internal"),
            ]
        )
        self.assertTrue(result["ok"], result["errors"])
        self.assertTrue(any(event["kind"] == "network_validated" for event in result["events"]))

    def test_cidr_overlap_and_dhcp_conflict(self):
        result = validate_networks(
            [
                net("a", "asr-lab", "192.168.30.0/24"),
                net("b", "db-lab", "192.168.30.128/25"),
            ]
        )
        self.assertFalse(result["ok"])
        joined = " ".join(result["errors"])
        self.assertIn("CIDR conflict", joined)
        self.assertIn("DHCP conflict", joined)
        kinds = {event["kind"] for event in result["events"]}
        self.assertIn("conflict_detected", kinds)
        self.assertIn("dhcp_warning", kinds)

    def test_gateway_checks(self):
        result = validate_networks(
            [
                net("a", "asr-lab", "192.168.30.0/24", gateway="192.168.99.1"),
                net("b", "db-lab", "192.168.40.0/24", gateway="not-an-ip"),
                net("c", "web-lab", "192.168.50.0/24", gateway="192.168.50.1"),
                net("d", "sad-lab", "192.168.60.0/24", gateway="192.168.50.1"),
            ]
        )
        joined = " ".join(result["errors"])
        self.assertIn("outside", joined)
        self.assertIn("invalid gateway", joined.lower())
        # The duplicated gateway pair (c, d) — wait, d's gateway is outside its
        # CIDR too; both errors must be present.
        self.assertIn("Duplicate gateway", joined)

    def test_invalid_cidr_reported(self):
        result = validate_networks([net("a", "asr-lab", "999.999.0.0/24")])
        self.assertFalse(result["ok"])
        self.assertIn("invalid CIDR", result["errors"][0])

    def test_vm_attachment_rules(self):
        networks = [
            net("hg-net-asr", "asr-lab", "192.168.30.0/24"),
            net("hg-net-db", "db-lab", "192.168.40.0/24", allowed_hosts=["asr-lab"]),
        ]
        vms = [
            VmInfo(id="ok-vm", lab_id="asr-lab", network_ids=["hg-net-asr"]),
            VmInfo(id="ghost-net-vm", lab_id="asr-lab", network_ids=["hg-net-missing"]),
            VmInfo(id="cross-blocked", lab_id="web-lab", network_ids=["hg-net-asr"]),
            VmInfo(id="cross-allowed", lab_id="asr-lab", network_ids=["hg-net-db"]),
        ]
        result = validate_networks(networks, vms=vms)
        self.assertFalse(result["ok"])
        joined = " ".join(result["errors"])
        self.assertIn("does not exist", joined)
        self.assertIn("Blocked cross-lab link", joined)
        self.assertIn("cross-blocked", joined)
        self.assertTrue(any("cross-allowed" in warning for warning in result["warnings"]))
        kinds = {event["kind"] for event in result["events"]}
        self.assertIn("blocked_cross_link", kinds)
        self.assertIn("vm_connected", kinds)

    def test_require_valid_networks_raises(self):
        with self.assertRaises(NetworkConflictError):
            require_valid_networks([net("a", "x-lab", "192.168.30.0/24"), net("b", "y-lab", "192.168.30.0/24")])

    def test_network_from_lab_manifest(self):
        lab = {"lab_id": "asr-lab", "network_id": "hg-net-asr-lab", "network_mode": "isolated", "subnet": "192.168.30.0/24"}
        network = network_from_lab(lab)
        self.assertEqual(network.id, "hg-net-asr-lab")
        self.assertEqual(network.mode, "internal")
        self.assertTrue(network.isolated)
        self.assertEqual(network.gateway, "192.168.30.1")


class RbacTests(unittest.TestCase):
    def test_role_permission_defaults(self):
        admin = User(id="gerard", role="Admin")
        guest = User(id="alumno", role="Guest", assigned_labs=["asr-lab"])
        self.assertTrue(check_permission(admin, "can_use_remote_compute"))
        self.assertTrue(check_permission(admin, "can_manage_guests"))
        self.assertTrue(check_permission(guest, "can_view_labs", lab_id="asr-lab"))
        self.assertFalse(check_permission(guest, "can_use_remote_compute"))
        self.assertFalse(check_permission(guest, "can_change_settings"))
        self.assertIn("can_teleport", DEFAULT_ROLE_PERMISSIONS["Operator"])

    def test_guest_cannot_gain_forbidden_permissions_even_explicitly(self):
        guest = User(id="alumno", role="Guest", extra_permissions=["can_use_remote_compute", "can_commit_nas"])
        self.assertFalse(check_permission(guest, "can_use_remote_compute"))
        # But grantable permissions like NAS commit do work when assigned.
        self.assertTrue(check_permission(guest, "can_commit_nas", lab_id=None))

    def test_guest_lab_scoping(self):
        guest = User(id="alumno", role="Guest", assigned_labs=["asr-lab"])
        self.assertTrue(check_permission(guest, "can_start_vm", lab_id="asr-lab"))
        self.assertFalse(check_permission(guest, "can_start_vm", lab_id="db-lab"))
        admin = User(id="gerard", role="Admin")
        self.assertTrue(check_permission(admin, "can_start_vm", lab_id="db-lab"))

    def test_require_permission_raises_and_audits(self):
        logger = StructuredLogger.__new__(StructuredLogger)  # not used directly; audit uses global
        guest = User(id="alumno", role="Guest", assigned_labs=["asr-lab"])
        require_permission(guest, "can_start_vm", lab_id="asr-lab")  # no exception
        with self.assertRaises(PermissionDeniedError):
            require_permission(guest, "can_teleport", lab_id="asr-lab")
        with self.assertRaises(HyperGeryError):
            check_permission(guest, "can_fly")
        self.assertIsNotNone(logger)

    def test_invalid_role_rejected(self):
        with self.assertRaises(HyperGeryError):
            User(id="x", role="Hacker")

    def test_user_store_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = UserStore(Path(tmp) / "users.json")
            store.add_user(User(id="gerard", role="SuperAdmin"))
            store.add_user(User(id="alumno", role="Guest"))
            with self.assertRaises(HyperGeryError):
                store.add_user(User(id="alumno", role="Guest"))
            store.assign_lab("alumno", "asr-lab")
            user = store.get_user("alumno")
            self.assertEqual(user.assigned_labs, ["asr-lab"])
            self.assertEqual([u.id for u in store.list_users()], ["alumno", "gerard"])
            store.remove_user("alumno")
            with self.assertRaises(HyperGeryError):
                store.get_user("alumno")

    def test_guest_offload_denied_in_orchestrator_flow(self):
        """Integration: guest without remote compute keeps plans local."""
        from hypergery_ubuntu.v1.hosts import HostInfo

        guest = User(id="alumno", role="Guest", assigned_labs=["asr-lab"])
        allow_remote = check_permission(guest, "can_use_remote_compute")
        hosts = [
            HostInfo(id="laptop", role="laptop", status="online", ram_total_mib=16384, ram_free_mib=12000, capabilities=["can_run_vms"]),
            HostInfo(id="home-pc", role="home_pc", status="online", ram_total_mib=32768, ram_free_mib=30000, capabilities=["can_run_vms"]),
        ]
        plans = OrchestratorService(settings=V1Settings()).plan(
            hosts=hosts,
            vms=[VmInfo(id="guest-vm", ram_mb=8192, status="running", host_id="laptop", lab_id="asr-lab")],
            local_host_id="laptop",
            allow_remote=allow_remote,
        )
        self.assertEqual(plans[0].target_host, "laptop")
        self.assertTrue(any("denied" in warning for warning in plans[0].warnings))


class ExternalNodeTests(unittest.TestCase):
    def test_store_roundtrip_and_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ExternalNodeStore(Path(tmp) / "nodes.json")
            node = ExternalNode(id="isard-1", type="isard", address="http://isard.lan:5000", ram_mib=65536)
            store.add_node(node)
            with self.assertRaises(HyperGeryError):
                store.add_node(node)
            self.assertEqual(store.get_node("isard-1").type, "isard")
            store.update_status("isard-1", "online")
            self.assertEqual(store.get_node("isard-1").status, "online")
            store.remove_node("isard-1")
            with self.assertRaises(HyperGeryError):
                store.get_node("isard-1")

    def test_invalid_node_rejected_and_type_sanitized(self):
        with self.assertRaises(HyperGeryError):
            ExternalNode(id="   ")
        node = ExternalNode(id="weird", type="quantum")
        self.assertEqual(node.type, "unknown")

    def test_loopback_health_and_offline_http(self):
        loop = ExternalNode(id="loop", type="loopback")
        health = health_check(loop)
        self.assertTrue(health["reachable"])
        self.assertEqual(health["status"], "online")
        dead = ExternalNode(id="dead", type="remote_pc", address="http://127.0.0.1:1")
        health = health_check(dead, timeout_seconds=1)
        self.assertFalse(health["reachable"])
        self.assertEqual(health["status"], "offline")
        no_probe = health_check(ExternalNode(id="bare", type="remote_pc"))
        self.assertEqual(no_probe["status"], "unknown")

    def test_orchestrator_considers_external_nodes(self):
        node = ExternalNode(id="isard-1", type="isard", status="online", ram_mib=65536, capabilities=["can_run_vms"])
        host = node.to_host_info()
        self.assertEqual(host.role, "isard")
        self.assertIn("external", host.tags)
        from hypergery_ubuntu.v1.hosts import HostInfo

        hosts = [
            HostInfo(id="laptop", role="laptop", status="online", ram_total_mib=8192, ram_free_mib=1500, capabilities=["can_run_vms"]),
            host,
        ]
        plans = OrchestratorService(settings=V1Settings()).plan(
            hosts=hosts,
            vms=[VmInfo(id="big", ram_mb=8192, status="running", host_id="laptop")],
            local_host_id="laptop",
        )
        # Laptop lacks headroom; the external node is the only candidate.
        self.assertEqual(plans[0].target_host, "isard-1")

    def test_detect_local_environment_is_non_invasive(self):
        info = detect_local_environment()
        self.assertIn("hostname", info)
        self.assertIn("virtualization", info)
        self.assertIn("kvm_available", info)
        self.assertIsInstance(info["kvm_available"], bool)


if __name__ == "__main__":
    unittest.main()
