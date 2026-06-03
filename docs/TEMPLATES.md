# HyperGery Templates

HyperGery v0.3.0 includes a full Templates Manager UI backed by `TemplateStore`.

## Qt Templates Manager

The Templates tab in the left panel has two sub-tabs: **VM Templates** and **Lab Templates**.

### VM Templates sub-tab

- Table shows: Name, ID, OS, RAM, vCPUs, Disk, Net, Display.
- Detail panel below the table shows all fields of the selected template.
- Buttons: **New VM Template**, **Import**, **Refresh**, **Delete**, **Export**, **Create VM from Template** (disabled — coming next release).

### Lab Templates sub-tab

- Table shows: Name, ID, Net, VMs (count), Desc/Notes.
- Detail panel below shows all fields of the selected template.
- Buttons: **New Lab Template**, **Import**, **Refresh**, **Delete**, **Export**, **Create Lab from Template** (disabled — coming next release).

### New VM Template dialog

Fields: Name, Template ID (auto-preview, read-only), OS Type, RAM MiB, vCPUs, Disk GiB, Network, Display, Notes. Create button disabled until Name produces a valid template_id.

### New Lab Template dialog

Fields: Name, Template ID (auto-preview), Description, Network, Notes. Initial VM list is empty; VM composition is planned for a future sub-task.

### Create VM from Template

Select a VM template and click **Create VM from Template**. The wizard opens with pre-filled values:

- OS type, RAM MiB, vCPUs, Disk GiB, Network mode, Display — from the template.
- Name and Boot ISO — entered by the user (ISO is required; no VM is created without one).
- Lab ID — editable (defaults to `default-lab`).

After the VM is created successfully, the template's `template_id` is appended to the lab manifest's `templates_used` list.

### Create Lab from Template

Select a lab template and click **Create Lab from Template**. A dialog opens with:

- Template name/id shown for reference.
- New lab name (required), Description (pre-filled from template, editable).
- Network mode pre-filled from template, editable.
- Live preview of lab_id, libvirt network, bridge, subnet.
- Planned VMs listed (informational only — VMs are **not created automatically**).

The lab is created via `LabStore`. Its `templates_used` field records the source template. VMs listed in the template are shown but must be created individually via **New VM** or **Create VM from Template**.

### Delete dialogs

Both VM and Lab delete dialogs require typing the exact `template_id` before enabling the Delete button. Only the JSON file is removed — no VMs or labs are affected.

### Export / Import

- Export: saves the template JSON to a user-selected path via `QFileDialog`.
- Import: reads a JSON file, validates it via `validate_vm_template` / `validate_lab_template`, and rejects imports that would collide with an existing `template_id`.
- Activity log records every operation.

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

Valid values: `os_type` ∈ {linux, windows, other}, `network_mode` ∈ {nat, isolated}, `display` ∈ {spice, vnc}.

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

## Not yet implemented

- Create VM from template (UI flow).
- Create Lab from template (UI flow).
- Edit template fields in place (no `update` method on `TemplateStore`; use delete + re-create).
