# Contributing to HyperGery

Thanks for helping improve HyperGery.

## Development Setup

Install Ubuntu dependencies:

```bash
./scripts/install-ubuntu-deps.sh
```

Run the app:

```bash
./scripts/dev-run.sh
```

Run checks:

```bash
python3 -m compileall hypergery-ubuntu
cd hypergery-ubuntu
python3 -m unittest discover -s tests
cd ..
bash -n scripts/dev-run.sh scripts/install-ubuntu-deps.sh scripts/install-desktop-launcher.sh scripts/preflight.sh scripts/acceptance-ubuntu.sh scripts/acceptance-real-host.sh
```

## Issues and Pull Requests

- Open an issue before large changes.
- Keep pull requests focused.
- Include the command output for tests or real-host validation when behavior touches libvirt, QEMU, storage, networks, console, snapshots, clone, or delete.
- Do not add Android Hub, NAS sync, IsardVDI, P2P/offload, live migration, GPU shadowing, or RBAC work to v0.1.x maintenance changes.

## Do Not Commit Runtime or Secrets

Never commit:

- ISO files.
- qcow2/img/vdi/vmdk/ova/ovf/hgd VM disk or appliance files.
- HyperGery runtime directories.
- Logs.
- `.env` files.
- API tokens.
- SSH keys.
- Certificates.
- Private lab/student/customer data.

The `.gitignore` blocks common unsafe files, but contributors are still responsible for checking `git status` and `git diff --cached --name-only` before committing.
