# HyperGery Lab Automation

HyperGery v0.4.0 introduces guided lab instantiation: create a complete lab environment with one or more VMs from a Lab Template, with ISO selection per VM and transactional rollback on failure.

## Overview

A **Lab Template** describes a reusable lab structure: network topology, a list of planned VMs with their resource profiles, and optional references to VM Templates.

**Lab Automation** turns a Lab Template into a real running environment in three steps:

1. Name the new lab instance and confirm the network preview.
2. Map an ISO to each planned VM that requires one.
3. Review and confirm — HyperGery creates the lab and all VMs sequentially.

## Planned VMs

Each planned VM in a lab template has:

- **name** — unique within the template; becomes the libvirt domain name.
- **os_type**, **ram_mib**, **vcpus**, **disk_gb**, **display** — resource profile.
- **template_id** (optional) — reference to a VM Template; defaults are resolved from the VM template and overridden by the planned VM's own values.
- **iso_required** (default `true`) — whether an ISO must be provided at instantiation.
- **role** (optional) — descriptive label like `server`, `client`, `router`.
- **notes** (optional) — free-text.

## ISO Mapping

At instantiation time the wizard shows all planned VMs in a table. For each VM with `iso_required = true`, the user must select a local ISO file. Multiple VMs can share the same ISO. VMs with `iso_required = false` are created without a boot image (useful for VMs that boot from network or are imported later).

## Dry Run

`TemplateStore.instantiate_lab_template(..., dry_run=True)` validates all inputs (missing ISOs, invalid names, file existence) and returns a plan dict without creating anything:

```python
result = template_store.instantiate_lab_template(
    "asr-lab",
    "ASR Instance",
    {"hg-v04-ad-server": "/path/to/ubuntu.iso", "hg-v04-client": "/path/to/ubuntu.iso"},
    dry_run=True,
)
# result["errors"] = []
# result["vm_plans"] = [{"name": "hg-v04-ad-server", "resolved": {...}, ...}, ...]
# result["lab"] = None  (nothing created)
```

## Transactional Rollback

If any VM creation fails mid-way:

1. Already-created VMs are deleted (including their qcow2 disks).
2. The lab manifest directory is removed.
3. If rollback itself fails (e.g. a disk cannot be deleted), the failure is surfaced as a warning with the names of affected VMs for manual cleanup.

The UI shows errors and warnings in the activity log. No partial state is silently left behind.

## Default Resolution Order

For each planned VM, resource defaults are resolved in this order (later values win):

1. HyperGery built-in defaults (linux, 4096 MiB, 2 vCPUs, 40 GB, nat, spice).
2. Values from the referenced VM Template (`template_id` field), if present and if the template exists.
3. Explicit values set on the planned VM itself.

This means a planned VM can specify only the fields that differ from its VM template, keeping lab templates concise.

## Editing Lab Templates

After creating a lab template, planned VMs can be added, edited (by removing and re-adding), or removed via **Edit Lab Template** in the UI:

1. Select the lab template.
2. Click **Edit**.
3. In the Planned VMs section, click **Add Planned VM…** to open a dialog with all VM fields.
4. Select a row and click **Remove Selected** to delete a planned VM.
5. Click **Save** — the template is updated immediately on disk.

## Lab Duplication with VM Cloning

The **Duplicate Lab** dialog enables the **Clone VMs too** checkbox when the source lab has VMs. If checked:

- All VMs in the source lab must be shut off.
- Each VM's qcow2 disk is converted and copied to a new path (`qemu-img convert`).
- New libvirt domains are created with independent disks and new UUIDs and MAC addresses.
- The new lab manifest records the cloned VMs.
- Runs in a background worker — does not block the UI.

If any VM is running when Clone VMs is requested, the operation fails before creating anything.

## Smoke Test (v0.4.0)

Prerequisites: real Ubuntu KVM host, real ISO file.

```text
Test names used:
  hg-v04-asr-template  (lab template)
  hg-v04-ubuntu-srv    (VM template, optional)
  hg-v04-asr-lab       (instantiated lab)
  hg-v04-ad-server     (VM created from template)
  hg-v04-client        (VM created from template)
```

Steps:

1. **Create VM template** `hg-v04-ubuntu-srv` (OS=linux, RAM=4096, vCPUs=2, Disk=40).

2. **Create lab template** `hg-v04-asr-template` (Network=isolated).
   - Edit it and add two planned VMs:
     - `hg-v04-ad-server`, template_id=hg-v04-ubuntu-srv, iso_required=true, role=server.
     - `hg-v04-client`, ram_mib=2048, disk_gb=20, iso_required=true, role=client.

3. **Select lab template** → click **Create Lab from Template**.
   - Page 1: Enter name `ASR Lab 01`; confirm preview shows lab_id and subnet.
   - Page 2: Browse ISO for both `hg-v04-ad-server` and `hg-v04-client`.
   - Page 3: Review — confirm both VMs listed.
   - Click **Create Lab** — activity log shows progress.

4. **Verify** in Instances tab: `asr-lab-01` appears with two VMs.
   - Lab details show `templates_used = hg-v04-asr-template`.

5. **Start** `hg-v04-ad-server` → Open Console → confirm BIOS/installer appears.

6. **Shut off** → **Duplicate Lab** with Clone VMs checked.
   - Confirm new lab appears with cloned VMs.

7. **Cleanup**: delete both labs and their VMs; delete both templates.

## Limitations

- Auto-create VMs from Lab Template via **CLI** is not yet implemented.
- Planned VM editing is add/remove only (no inline field edits — delete and re-add to change a VM's resources).
- If a planned VM name conflicts with an existing libvirt domain, VM creation fails and rollback kicks in.
- Lab Templates do not verify referenced VM Template IDs at creation time (only a warning at instantiation if not found).
