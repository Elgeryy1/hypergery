# HyperGery Hub Docker

Run the HyperGery Hub on the NAS/QNAP:

```bash
cd /share/CACHEDEV2_DATA/Gerard/proyectos_hacen_bulto_en_CV/miversiondevirtualbox/docker
cp .env.example .env
mkdir -p /share/CACHEDEV2_DATA/Gerard/hypergery/migrations
docker compose up -d
docker compose logs -f
curl http://192.168.1.150:8765/health
```

For local Ubuntu testing, set `HYPERGERY_NAS_ROOT` in `.env` to the mounted NAS data path:

```bash
HYPERGERY_NAS_ROOT=/mnt/hypergery-nas/hypergery
```

Notes:

- No passwords, SSH keys, or SMB credentials are stored by this compose file.
- The Hub SQLite DB is persisted in `docker/data`.
- VM migration packages are stored under `HYPERGERY_NAS_ROOT/migrations`.
- The container sees migration packages under `/hypergery/migrations`.
- The Hub API listens on port `8765`.

Useful validation:

```bash
cd docker
docker compose config
docker compose build
docker compose up -d
docker compose logs -f
curl http://192.168.1.150:8765/health
curl http://192.168.1.150:8765/hosts
```
