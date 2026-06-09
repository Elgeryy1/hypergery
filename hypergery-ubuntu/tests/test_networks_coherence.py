"""Redes coherentes v1.1: HG-BUG-0009 (lógicas vs reales), 0012 (colisión de
octetos) y 0016 (TOCTOU en ensure_network)."""

from __future__ import annotations

import unittest

from hypergery_ubuntu.backend import (
    HG_NETWORK_OCTETS,
    CommandResult,
    HyperGeryBackend,
    HyperGeryError,
    allocate_network_octet,
    derive_network_octet,
)
from hypergery_ubuntu.v1.networks import network_from_lab, networks_from_labs, validate_networks


def _find_colliding_lab_ids() -> tuple[str, str, int]:
    """Dos lab_ids cuyo octeto hash coincide (existen por cumpleaños)."""
    seen: dict[int, str] = {}
    for index in range(10000):
        lab_id = f"lab-{index}"
        octet = derive_network_octet(lab_id, "nat")
        if octet in seen:
            return seen[octet], lab_id, octet
        seen[octet] = lab_id
    raise AssertionError("no collision found in 10000 lab ids")


class OctetAllocationTests(unittest.TestCase):
    def test_base_octet_is_deterministic_and_in_space(self):
        for lab_id in ("default-lab", "asr-lab", "x"):
            for mode in ("nat", "isolated"):
                octet = derive_network_octet(lab_id, mode)
                self.assertEqual(octet, derive_network_octet(lab_id, mode))
                self.assertIn(octet, HG_NETWORK_OCTETS)
                self.assertNotEqual(octet, 122)

    def test_free_base_octet_is_kept(self):
        octet = derive_network_octet("default-lab", "nat")
        self.assertEqual(allocate_network_octet("default-lab", "nat", set()), octet)

    def test_collision_probes_to_next_free_octet(self):
        lab_a, lab_b, octet = _find_colliding_lab_ids()
        allocated = allocate_network_octet(lab_b, "nat", {octet})
        self.assertNotEqual(allocated, octet)
        self.assertIn(allocated, HG_NETWORK_OCTETS)
        # Determinista: mismo estado → misma asignación.
        self.assertEqual(allocated, allocate_network_octet(lab_b, "nat", {octet}))

    def test_exhausted_space_raises(self):
        with self.assertRaises(HyperGeryError):
            allocate_network_octet("default-lab", "nat", set(HG_NETWORK_OCTETS))


class LogicalNetworksMatchRealTests(unittest.TestCase):
    def test_lab_without_subnet_derives_the_real_libvirt_subnet(self):
        # HG-BUG-0009: antes esto daba "missing CIDR" en el tab de Redes.
        lab = {"lab_id": "asr-lab", "network_mode": "nat"}
        network = network_from_lab(lab)
        octet = derive_network_octet("asr-lab", "nat")
        self.assertEqual(network.cidr, f"192.168.{octet}.0/24")
        self.assertEqual(network.gateway, f"192.168.{octet}.1")
        self.assertIn("real", network.notes)

    def test_isolated_lab_derives_from_isolated_mode(self):
        lab = {"lab_id": "asr-lab", "network_mode": "isolated"}
        network = network_from_lab(lab)
        octet = derive_network_octet("asr-lab", "isolated")
        self.assertEqual(network.cidr, f"192.168.{octet}.0/24")
        self.assertTrue(network.isolated)

    def test_explicit_subnet_is_untouched(self):
        lab = {"lab_id": "asr-lab", "network_mode": "nat", "subnet": "10.10.0.0/24"}
        network = network_from_lab(lab)
        self.assertEqual(network.cidr, "10.10.0.0/24")
        self.assertEqual(network.gateway, "10.10.0.1")
        self.assertEqual(network.notes, "")

    def test_two_plain_labs_validate_without_spurious_errors(self):
        labs = [
            {"lab_id": "lab-uno", "network_mode": "nat"},
            {"lab_id": "lab-dos", "network_mode": "nat"},
        ]
        networks = networks_from_labs(labs)
        result = validate_networks(networks)
        self.assertTrue(result["ok"], result["errors"])

    def test_hash_collision_does_not_produce_false_conflict(self):
        # HG-BUG-0012 en el modelo lógico: dos labs con el mismo octeto hash
        # reciben subredes distintas.
        lab_a, lab_b, _octet = _find_colliding_lab_ids()
        networks = networks_from_labs(
            [{"lab_id": lab_a, "network_mode": "nat"}, {"lab_id": lab_b, "network_mode": "nat"}]
        )
        cidrs = {network.cidr for network in networks}
        self.assertEqual(len(cidrs), 2, cidrs)
        self.assertTrue(validate_networks(networks)["ok"])

    def test_explicit_subnets_reserve_their_octet_first(self):
        lab_a, lab_b, octet = _find_colliding_lab_ids()
        labs = [
            {"lab_id": lab_b, "network_mode": "nat"},
            {"lab_id": lab_a, "network_mode": "nat", "subnet": f"192.168.{octet}.0/24"},
        ]
        networks = networks_from_labs(labs)
        by_lab = {network.lab_id: network for network in networks}
        self.assertEqual(by_lab[lab_a].cidr, f"192.168.{octet}.0/24")
        self.assertNotEqual(by_lab[lab_b].cidr, f"192.168.{octet}.0/24")
        self.assertTrue(validate_networks(networks)["ok"])


class _ScriptedBackend(HyperGeryBackend):
    """Backend con virsh simulado por guion: {(args[0], args[1] if any): result}."""

    def __init__(self, script):
        super().__init__()
        self.script = script
        self.calls = []
        self.defined_xml = []

    def virsh(self, args, *, timeout=120, check=True):
        self.calls.append(list(args))
        if args[0] == "net-define":
            from pathlib import Path

            self.defined_xml.append(Path(args[1]).read_text(encoding="utf-8"))
            result = self.script.get("net-define", CommandResult(["virsh", *args], 0, "", ""))
        else:
            key = (args[0], args[-1])
            result = self.script.get(key) or self.script.get(args[0]) or CommandResult(["virsh", *args], 0, "", "")
        if callable(result):
            result = result()
        if check and result.returncode != 0:
            raise HyperGeryError(f"virsh {' '.join(args)} failed: {result.stderr}")
        return result


def _ok(stdout: str = "") -> CommandResult:
    return CommandResult(["virsh"], 0, stdout, "")


def _fail(stderr: str = "boom") -> CommandResult:
    return CommandResult(["virsh"], 1, "", stderr)


class EnsureNetworkTests(unittest.TestCase):
    def test_define_collision_with_existing_network_probes_new_octet(self):
        lab_a, lab_b, octet = _find_colliding_lab_ids()
        backend = _ScriptedBackend({})
        other_name = backend.network_name(lab_a, "nat")
        our_name = backend.network_name(lab_b, "nat")
        backend.script = {
            ("net-list", "--name"): _ok(f"{other_name}\n"),
            ("net-dumpxml", other_name): _ok(
                f"<network><name>{other_name}</name><bridge name='hgbr1234567'/><ip address='192.168.{octet}.1'/></network>"
            ),
            ("net-info", our_name): _fail("no network"),
            "net-define": _ok(),
            "net-start": _ok(),
        }
        backend.ensure_network(lab_b, "nat")
        self.assertEqual(len(backend.defined_xml), 1)
        self.assertNotIn(f"192.168.{octet}.1", backend.defined_xml[0])
        expected = allocate_network_octet(lab_b, "nat", {octet})
        self.assertIn(f"192.168.{expected}.1", backend.defined_xml[0])

    def test_toctou_net_start_already_active_is_not_an_error(self):
        backend = _ScriptedBackend({})
        name = backend.network_name("default-lab", "nat")
        bridge = backend.bridge_name("default-lab", "nat")
        ip = backend.network_ip_address("default-lab", "nat")
        states = iter(
            [
                _ok("Active:      no\n"),  # net-info inicial
                _ok("Active:      no\n"),  # tras reconcile
                _ok("Active:      no\n"),  # chequeo de activación
                _ok("Active:      yes\n"),  # re-chequeo tras fallo de net-start
            ]
        )
        backend.script = {
            ("net-list", "--name"): _ok(f"{name}\n"),
            ("net-dumpxml", name): _ok(
                f"<network><name>{name}</name><bridge name='{bridge}'/><ip address='{ip}'/></network>"
            ),
            ("net-info", name): lambda: next(states),
            ("net-start", name): _fail(f"error: network '{name}' is already active"),
            ("net-autostart", name): _ok(),
        }
        self.assertEqual(backend.ensure_network("default-lab", "nat"), name)

    def test_toctou_net_define_lost_race_is_benign(self):
        backend = _ScriptedBackend({})
        name = backend.network_name("default-lab", "nat")
        infos = iter(
            [
                _fail("no network"),  # net-info inicial: no existe
                _ok("Active:      no\n"),  # otro proceso la definió: re-chequeo tras fallo de define
                _ok("Active:      yes\n"),  # chequeo de activación
            ]
        )
        backend.script = {
            ("net-list", "--name"): _ok(""),
            ("net-info", name): lambda: next(infos),
            "net-define": _fail("error: network already exists"),
            ("net-autostart", name): _ok(),
        }
        self.assertEqual(backend.ensure_network("default-lab", "nat"), name)

    def test_net_start_real_failure_raises(self):
        backend = _ScriptedBackend({})
        name = backend.network_name("default-lab", "nat")
        bridge = backend.bridge_name("default-lab", "nat")
        ip = backend.network_ip_address("default-lab", "nat")
        backend.script = {
            ("net-list", "--name"): _ok(f"{name}\n"),
            ("net-dumpxml", name): _ok(
                f"<network><name>{name}</name><bridge name='{bridge}'/><ip address='{ip}'/></network>"
            ),
            ("net-info", name): _ok("Active:      no\n"),
            ("net-start", name): _fail("error: bridge creation failed"),
        }
        with self.assertRaises(HyperGeryError):
            backend.ensure_network("default-lab", "nat")

    def test_reconcile_keeps_reassigned_ip_that_does_not_collide(self):
        # HG-BUG-0012: una red reasignada por colisión no debe reciclarse en
        # cada ensure_network.
        backend = _ScriptedBackend({})
        name = backend.network_name("default-lab", "nat")
        bridge = backend.bridge_name("default-lab", "nat")
        base_octet = derive_network_octet("default-lab", "nat")
        other = next(o for o in HG_NETWORK_OCTETS if o != base_octet)
        backend.script = {
            ("net-dumpxml", name): _ok(
                f"<network><name>{name}</name><bridge name='{bridge}'/><ip address='192.168.{other}.1'/></network>"
            ),
        }
        backend.reconcile_existing_network(name, bridge, f"192.168.{base_octet}.1", used_octets=set())
        self.assertNotIn(["net-undefine", name], backend.calls)

    def test_reconcile_recycles_ip_that_collides_with_another_network(self):
        backend = _ScriptedBackend({})
        name = backend.network_name("default-lab", "nat")
        bridge = backend.bridge_name("default-lab", "nat")
        base_octet = derive_network_octet("default-lab", "nat")
        other = next(o for o in HG_NETWORK_OCTETS if o != base_octet)
        backend.script = {
            ("net-dumpxml", name): _ok(
                f"<network><name>{name}</name><bridge name='{bridge}'/><ip address='192.168.{other}.1'/></network>"
            ),
            ("net-info", name): _ok("Active:      no\n"),
        }
        backend.reconcile_existing_network(name, bridge, f"192.168.{base_octet}.1", used_octets={other})
        self.assertIn(["net-undefine", name], backend.calls)


if __name__ == "__main__":
    unittest.main()
