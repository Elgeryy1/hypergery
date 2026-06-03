# HyperGery Templates

HyperGery v0.3.0 adds backend storage for reusable VM and lab templates. The Qt UI for templates is intentionally not implemented yet.

## VM Templates

Location:

```text
~/.local/share/hypergery/templates/vm/
```

Schema:

```json
{
  "schema_version": 1,
  "template_id": "ubuntu-base",
  "name": "Ubuntu Base",
  "os_type": "linux",
  "ram_mib": 4096,
  "vcpus": 2,
  "disk_gb": 40,
  "network_mode": "nat",
  "display": "spice",
  "notes": ""
}
```

VM templates do not include private ISO paths by default.

## Lab Templates

Location:

```text
~/.local/share/hypergery/templates/lab/
```

Schema:

```json
{
  "schema_version": 1,
  "template_id": "classroom",
  "name": "Classroom",
  "description": "Reusable classroom lab",
  "network_mode": "nat",
  "vms": [
    {
      "name": "student",
      "template_id": "ubuntu-base",
      "ram_mib": 4096,
      "vcpus": 2,
      "disk_gb": 40,
      "os_type": "linux",
      "display": "spice"
    }
  ],
  "notes": ""
}
```

## CLI

```bash
python -m hypergery_ubuntu.cli template list vm
python -m hypergery_ubuntu.cli template show vm ubuntu-base
python -m hypergery_ubuntu.cli template delete vm ubuntu-base

python -m hypergery_ubuntu.cli template list lab
python -m hypergery_ubuntu.cli template show lab classroom
python -m hypergery_ubuntu.cli template delete lab classroom
```

Template creation APIs exist in the backend foundation. A richer UI and VM creation from templates are planned for the next v0.3 UI slice.
