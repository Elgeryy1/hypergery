# Security Policy

HyperGery is early-stage software. Please treat VM disks, ISO files, lab manifests, and logs as potentially sensitive.

## Do Not Share Sensitive Data

Do not upload or commit:

- Credentials or tokens.
- `.env` files.
- SSH keys or certificates.
- Private ISOs.
- VM disks or snapshots.
- Student, customer, or lab data.
- Logs that reveal private paths, hostnames, usernames, or lab contents.

## Reporting Security Issues

While the project is small, please report suspected security issues through GitHub issues with minimal sensitive detail. If the report requires private data, describe the class of problem first and avoid attaching secrets or private disks.

## Runtime Safety

HyperGery uses `virsh`, `qemu-img`, and viewer tools with argument lists instead of shell-concatenated command strings. It validates VM and lab names, avoids deleting unmanaged disks, and keeps runtime disks/logs outside the repository.

## Hub / API Network Exposure (v1.0.x)

The HyperGery Hub control plane and the v1 HTTP API have **no authentication and no TLS** in the v1.0.x line. Treat them as trusted-LAN-only services:

- Anyone who can reach the Hub port can queue commands (including remote **Force Off**), upload or delete migration packages in staging, and read the host/VM inventory.
- The Hub binds to **`127.0.0.1` by default**; it is reachable from other hosts only if you explicitly bind a routable address (`--host 0.0.0.0` or `HYPERGERY_HUB_HOST`). The v1 API similarly requires an explicit `--allow-remote` to leave loopback.
- **Do not expose the Hub or API to the Internet or to an untrusted network.** Keep them on a trusted home/lab LAN; do not port-forward the Hub port.
- There is **no per-request authorization, rate limiting, or upload size limit** yet. Token authentication and TLS are planned for **v1.2** (`NEXT_STEPS_V12_SECURITY.md`).
