# HyperGery Templates

HyperGery v0.4.0 expands the Templates Manager with full lab instantiation, template editing, and planned VM management.

## Qt Templates Manager

The Templates tab in the left panel has two sub-tabs: **VM Templates** and **Lab Templates**.

### VM Templates sub-tab

- Table shows: Name, ID, OS, RAM, vCPUs, Disk, Net, Display.
- Detail panel below the table shows all fields of the selected template.
- Buttons: **New VM Template**, **Import**, **Refresh**, **Delete**, **Edit**, **Export**, **Create VM from Template**.

### Lab Templates sub-tab

- Table shows: Name, ID, Net, VMs (count), Desc/Notes.
- Detail panel below shows all fields of the selected template, including planned VMs count.
- Buttons: **New Lab Template**, **Import**, **Refresh**, **Delete**, **Edit**, **Export**, **Create Lab from Template**.

### New VM Template dialog

Fields: Name, Template ID (auto-preview, read-only), OS Type, RAM MiB, vCPUs, Disk GiB, Network, Display, Notes. Create button disabled until Name produces a valid template_id.

### New Lab Template dialog

Fields: Name, Template ID (auto-preview), Description, Network, Notes. The `vms` list starts empty; add planned VMs via the Edit Lab Template dialog after creation.

### Edit VM Template dialog

Pre-filled form showing the current values of the selected template. All fields except `template_id` and `schema_version` are editable. Saved immediately to the JSON file via `update_vm_template()`.

### Edit Lab Template dialog

Pre-filled form for name, description, network mode, and notes. Includes a Planned VMs list widget with **Add Planned VM…** and **Remove Selected** buttons. Adding a planned VM opens a sub-dialog to define VM name, role, OS type, RAM, vCPUs, disk, display, and `iso_required` flag.

### Create VM from Template

Select a VM template and click **Create VM from Template**. The wizard opens with pre-filled values:

- OS type, RAM MiB, vCPUs, Disk GiB, Network mode, Display — from the template.
- Name and Boot ISO — entered by the user (ISO is required; no VM is created without one).
- Lab ID — editable (defaults to `default-lab`).

After the VM is created successfully, the template's `template_id` is appended to the lab manifest's `templates_used` list.

### Create Lab from Template (v0.4.0 wizard)

Select a lab template and click **Create Lab from Template**. A 3-page wizard opens:

**Page 1 — Lab Identity**

- New lab name (required).
- Description (pre-filled from template, editable).
- Network mode (pre-filled from template, editable).
- Live preview of lab_id, libvirt network, bridge, and subnet.

**Page 2 — ISO Mapping**

- Table of all planned VMs with columns: ISO Path, VM Name, Role, RAM MiB, Required.
- Each VM with `iso_required = true` shows a Browse (…) button.
- VMs with `iso_required = false` can proceed without an ISO path.
- The Next button is disabled until all required-ISO VMs have a path entered.

**Page 3 — Review**

- Full summary: template, lab name, lab_id, network, all VMs with their ISO and resources.
- Explanation that VMs are created sequentially, with rollback on failure.
- **Create Lab** button executes the instantiation in a background worker.

On success, the lab appears in the Instances tab with `templates_used` recording the source template. On failure, already-created VMs and the lab manifest are removed (rollback). Partial rollback failures are surfaced as warnings.

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

Schema (v0.4.0):

```json
{
  "schema_version": 1,
  "template_id": "asr-lab",
  "name": "ASR Lab",
  "description": "Active Sniffing and Routing lab",
  "network_mode": "isolated",
  "vms": [
    {
      "name": "hg-v04-ad-server",
      "template_id": "ubuntu-base",
      "os_type": "linux",
      "ram_mib": 4096,
      "vcpus": 2,
      "disk_gb": 40,
      "display": "spice",
      "iso_required": true,
      "role": "server",
      "notes": "Active Directory server"
    },
    {
      "name": "hg-v04-client",
      "os_type": "linux",
      "ram_mib": 2048,
      "vcpus": 1,
      "disk_gb": 20,
      "display": "spice",
      "iso_required": true,
      "role": "client",
      "notes": ""
    }
  ],
  "notes": ""
}
```

### Planned VM fields

| Field | Required | Default | Description |
|---|---|---|---|
| `name` | yes | — | VM name (must be unique within the template) |
| `os_type` | yes | — | `linux`, `windows`, or `other` |
| `ram_mib` | yes | — | RAM in MiB (≥1) |
| `vcpus` | yes | — | vCPU count (≥1) |
| `disk_gb` | yes | — | Disk in GiB (≥1) |
| `display` | yes | — | `spice` or `vnc` |
| `template_id` | no | `""` | Optional VM template to inherit defaults from |
| `iso_required` | no | `true` | Whether an ISO is required at instantiation |
| `role` | no | `""` | Descriptive role (server, client, router…) |
| `notes` | no | `""` | Free-text notes |

If `template_id` is set, `_resolve_planned_vm()` merges VM template defaults before applying planned VM overrides. The planned VM's explicit values always win over the referenced template's defaults.

## Instantiation (backend)

`TemplateStore.instantiate_lab_template(template_id, new_lab_name, vm_iso_map, *, dry_run=False)`:

- `vm_iso_map`: `{vm_name: iso_path}` — ISO path per VM name.
- `dry_run=True`: validates all inputs and returns a plan with `errors`/`warnings` without creating anything.
- On error (missing ISO, non-existent ISO file, empty lab name): returns immediately with `errors` populated, no side effects.
- On success: creates the lab via `LabStore`, then creates each VM sequentially via `backend.create_vm()`, records `templates_used`, updates the lab manifest with the VM list.
- Rollback: if any VM creation fails, already-created VMs are deleted and the lab manifest directory is removed. If rollback itself fails, the error is surfaced as a warning with manual cleanup instructions.

## Template Editing

`TemplateStore.update_vm_template(template_id, **kwargs)` and `update_lab_template(template_id, **kwargs)`:

- All keyword arguments are applied to the existing template dict.
- `template_id` and `schema_version` are protected: passing them as kwargs is ignored.
- The updated dict is re-validated before writing, so invalid values raise `HyperGeryError`.

## CLI

```bash
python -m hypergery_ubuntu.cli template list vm
python -m hypergery_ubuntu.cli template show vm ubuntu-base
python -m hypergery_ubuntu.cli template delete vm ubuntu-base

python -m hypergery_ubuntu.cli template list lab
python -m hypergery_ubuntu.cli template show lab asr-lab
python -m hypergery_ubuntu.cli template delete lab asr-lab
```

CLI update/instantiate commands are not implemented yet (v0.5 target).

## Not yet implemented

- CLI `template update` and `template instantiate` commands.
- Auto-create planned VMs from lab template via CLI (UI only for now).
- Edit template fields via CLI (use delete + re-create as workaround).
