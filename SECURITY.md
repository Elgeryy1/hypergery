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

HyperGery v0.1.0 uses `virsh`, `qemu-img`, and viewer tools with argument lists instead of shell-concatenated command strings. It validates VM and lab names, avoids deleting unmanaged disks, and keeps runtime disks/logs outside the repository.
