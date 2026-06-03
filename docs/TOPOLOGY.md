# HyperGery Lab Topology

HyperGery v0.5.0 adds a visual topology view for each lab.

## Qt Topology Tab

When a lab is selected in the Instances tab, the Lab Details panel gains two sub-tabs:

- **Details** — existing text view (name, ID, network, subnet, bridge, VM count, templates used).
- **Topology** — `LabTopologyWidget`: QPainter canvas showing the lab network and its VMs.

### Topology canvas layout

```
┌──────────────────────────────────────────────────────────┐
│ [network node]       [vm-node]                           │
│  hg-net-asr-lab ───  hg-v04-ad-server  running  4G 2c   │
│  isolated            ─────────────────────────────────   │
│  192.168.30          hg-v04-client     shut off  2G 1c   │
└──────────────────────────────────────────────────────────┘
```

- **Network node** (left): shows the libvirt network name, network mode (NAT/ISOLATED), and subnet prefix.
- **VM nodes** (right): one card per VM, showing name, state (colour-coded), RAM, and vCPU count.
- **Connections**: cubic bezier lines from the network node to each VM.
- **Click a VM node** to select that VM in the main VM list and switch to the Details tab.

### VM state colours

| State | Colour |
|---|---|
| running | Green (#4CAF50) |
| shut off | Grey (#9E9E9E) |
| paused | Amber (#FFC107) |
| not created | Slate blue (#607D8B) |
| other / unknown | Orange-red (#FF5722) |

### "Not created" VMs

VMs listed in the lab manifest but absent from libvirt are shown with state `not created`. This happens when a planned VM was recorded in the manifest but its `create_vm` step failed or was never started.

## Topology Model

`build_lab_topology(lab: dict, vms: list[VmSummary]) -> dict`:

- Merges live VmSummary objects (from libvirt) with the lab manifest VM list.
- VMs present in both are marked `live=True`.
- Manifest-only VMs are marked `live=False`, `state="not created"`.
- VMs from other labs are excluded.
- Returns a serialisable dict (usable with `topology_to_json()`).

```python
{
    "lab_id": "asr-lab",
    "lab_name": "ASR Lab",
    "network_mode": "isolated",
    "network_id": "hg-net-asr-lab-isolated",
    "subnet": "192.168.30.0/24",
    "bridge_name": "hgbr1234567",
    "vms": [
        {
            "name": "hg-v04-ad-server",
            "state": "running",
            "ram_mib": 4096,
            "vcpus": 2,
            "live": true
        },
        {
            "name": "hg-v04-client",
            "state": "not created",
            "ram_mib": 0,
            "vcpus": 0,
            "live": false
        }
    ]
}
```

## CLI

```bash
python -m hypergery_ubuntu.cli lab-topology <lab_id>
```

Prints the topology as JSON. Useful for scripting, auditing, or exporting lab state.

## Not yet implemented

- Drag-and-drop repositioning of VM nodes.
- Topology export as PNG/SVG.
- Role badges on VM nodes (planned — role field exists in manifest VMs but not yet in VmSummary).
- Zoom/pan for large labs (currently all VMs fit in a vertical list).
