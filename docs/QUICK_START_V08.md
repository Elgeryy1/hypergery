# HyperGery v0.8 Quick Start

HyperGery v0.8 is the Remote Cluster Workflows release: control and observe
VMs on other hosts from one app, keep the Hub staging clean, and work with
labs as real multi-host workspaces. Everything flows
**App → Hub (NAS) → target Agent → libvirt**; the app never talks to a remote
libvirt directly, and there is no remote delete, remote shell, or remote
console.

Start from the [v0.7 Quick Start](QUICK_START_V07.md) for Hub deployment,
settings, and Hub Transfer migrations — all of that is unchanged. This guide
covers what is new in v0.8.

## 1. Update the Hub and the Agents

v0.8 adds Hub endpoints (`GET /packages`, `POST /packages/cleanup`,
`GET /commands`) and richer agent inventory (networks, MACs). Redeploy the
Hub container on the NAS and restart the agent on each host:

```bash
# Each host (agent as a user service):
systemctl --user restart hypergery-agent

# Verify the Hub:
curl http://192.168.1.150:8765/health
curl http://192.168.1.150:8765/commands
curl http://192.168.1.150:8765/packages
```

Old agents keep working against a new Hub (they just report fewer inventory
fields). A v0.7 Hub does not serve the new endpoints — the app shows
"Hub not reachable"-style errors only on the new pages, everything else keeps
working.

## 2. Remote VM Power Control + Details

**Remote Hosts → View VMs** on any online host:

- Select a VM to see its details: state, lab, RAM, vCPUs, disk paths, ISOs,
  display, MACs, networks, and the last inventory update (with a staleness
  warning if the agent has not refreshed recently).
- **Start** / **ACPI Shutdown** / **Force Off** queue a command on the Hub;
  the target agent validates it (allowlist, VM exists, state allows the
  action) and executes it. Force Off always asks for confirmation.
- The dialog shows the command id and polls until done/failed; completions
  are also recorded in the activity log.
- The Console button is disabled (remote console arrives later). There is no
  remote delete anywhere.

## 3. Commands Page

The **Commands** sidebar page is a read-only view of the Hub command queue:
id, target host, type, status (pending/running/done/failed), age, and
payload/result summaries. Filter by status, power commands, or migration
commands; copy the command id or full JSON result for debugging. Nothing can
be requeued, deleted, or executed from this page.

## 4. Hub Staging Maintenance

Interrupted or failed Hub Transfer migrations can leave orphan packages in
the Hub staging area. Inspect and clean them safely:

```bash
python -m hypergery_ubuntu.cli hub packages
python -m hypergery_ubuntu.cli hub cleanup-staging --older-than-hours 24 --dry-run
python -m hypergery_ubuntu.cli hub cleanup-staging --older-than-hours 24 --confirm
```

Or in the app: **Migrations → Hub Staging Maintenance** (Refresh / Dry Run
Cleanup / Cleanup Confirmed). Safety rules, always enforced server-side:

- Dry run is the default; real deletion needs `--confirm` / the confirmation
  dialog.
- Only temporary Hub staging packages are deleted. VMs and imported disks are
  never touched.
- Packages of active migrations and packages newer than the threshold
  (minimum 1 hour) are always skipped; failed-migration packages need
  `--include-failed`.

## 5. Labs Workspace

The **Labs** sidebar page is now a real workspace:

- One card per lab with live VM counts (running / shut off / paused /
  not created).
- The detail table combines local libvirt VMs and remote VMs from the Hub
  inventory, with host distribution and optional per-VM roles
  (router, firewall, dns, ad, server, db, web, client — set via
  **Set VM Role…**).
- **Start Lab** starts every shut off VM ("This will start N VMs across M
  hosts."), infrastructure first by role; **Shutdown Lab** sends ACPI shutdown
  to every running VM, clients first. Local VMs use the local backend; remote
  VMs queue Hub→Agent commands. Partial failures are listed per VM.
- Intentionally not available: lab-wide Force Off, lab-wide snapshots
  (planned), remote delete.

## 6. What v0.8 does NOT include

- True live RAM migration / HG-MEMDIFF.
- Remote console (disabled button, arrives later) and remote VNC exposure.
- Remote VM delete/undefine/disk deletion or any remote shell.
- Hub authentication — keep the Hub on the trusted LAN only.
- AutoBoost, Android Hub, IsardVDI, P2P transfer.
