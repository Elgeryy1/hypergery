"""Live migration REAL en caliente (v1.5): RAM + vCPU con la VM encendida.

Implementada sobre ``virsh migrate`` (que internamente llama a
``virDomainMigrateToURI3``) con ``VIR_MIGRATE_LIVE``: QEMU/KVM transfiere las
páginas de RAM iterativamente (pre-copy) con la VM ejecutándose; en el
switchover pausa unos milisegundos para las páginas sucias restantes + estado
de vCPU y dispositivos, y reanuda en el destino. La VM **nunca se apaga**.

Flags soportados (equivalencias libvirt):
- ``--live --persistent`` → VIR_MIGRATE_LIVE | VIR_MIGRATE_PERSIST_DEST
- el origen NO se undefine durante la migración: la fase ``activate``
  confirma el destino y solo entonces limpia el origen (semántica
  UNDEFINE_SOURCE controlada por nosotros).
- ``--copy-storage-all`` / ``--copy-storage-inc`` → VIR_MIGRATE_NON_SHARED_DISK
  / NON_SHARED_INC (block migration sin shared storage)
- ``--auto-converge`` / ``--postcopy`` → AUTO_CONVERGE / POSTCOPY
- ``--abort-on-error`` y rollback con ``virsh domjobabort`` → origen intacto
  y corriendo, destino limpio. **Nunca activa en dos hosts.**

Conectividad: SOLO URIs seguras (qemu+ssh:// o qemu+tls://; qemu+tcp:// se
rechaza). Una VM con GPU passthrough (<hostdev> PCI) se bloquea en preflight.
Progreso continuo vía ``virsh domjobinfo`` (datos/memoria
procesada/restante, velocidad, iteraciones, dirty rate) publicado por el
canal de progreso (TD-9), y downtime real medido con
``virsh domjobinfo --completed``.
"""

from __future__ import annotations

import re
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

from .errors import HyperGeryError
from .migration_engine import MigrationEngine, MigrationPhase
from .progress import ProgressChannel

SECURE_URI_SCHEMES = ("qemu+ssh://", "qemu+tls://")

JOBINFO_POLL_SECONDS = 1.0

# Filesystems donde el handoff del write-lock de imágenes de QEMU no es fiable
# (verificado en el UAT U10 de 2026-06-10 sobre un QNAP: durable handles SMB
# dejan al destino sin poder reanudar y al origen pausado). Para shared-storage
# usa NFS o un cluster FS; block migration no se ve afectada.
UNSUPPORTED_SHARED_STORAGE_FSTYPES = frozenset(
    {"cifs", "smb", "smb2", "smb3", "smbfs", "fuse.smb", "fuse.smbnetfs", "fuse.cifs"}
)


def disk_filesystem_type(path: str, mounts_path: str = "/proc/mounts") -> str:
    """Tipo de filesystem del punto de montaje que contiene ``path``.

    Longest-prefix match sobre /proc/mounts (solo lectura). Devuelve "" si no
    se puede determinar — el guard solo actúa sobre tipos positivamente
    identificados como no soportados, nunca por desconocimiento.
    """
    try:
        with open(mounts_path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return ""
    target = str(path)
    best_mount = ""
    best_type = ""
    for line in lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        mount_point = parts[1].replace("\\040", " ")
        if target == mount_point or target.startswith(mount_point.rstrip("/") + "/"):
            if len(mount_point) > len(best_mount):
                best_mount = mount_point
                best_type = parts[2]
    return best_type


@dataclass
class LiveMigrationPlan:
    vm_name: str
    target_uri: str
    shared_storage: bool | None = None  # None = auto-detect
    incremental_storage: bool = False  # --copy-storage-inc (base común)
    auto_converge: bool = True
    postcopy: bool = False
    bandwidth_mibps: int = 0  # 0 = sin límite
    timeout_seconds: int = 1800
    undefine_source_on_success: bool = True
    extra_warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        from ..backend import validate_vm_name

        self.vm_name = validate_vm_name(self.vm_name)
        uri = str(self.target_uri or "").strip()
        if not uri.startswith(SECURE_URI_SCHEMES):
            raise HyperGeryError(
                f"Insecure or unsupported migration URI: {uri!r}. "
                f"Only {', '.join(SECURE_URI_SCHEMES)} are allowed (TLS/SSH; use VPN/WireGuard for off-LAN)."
            )
        self.target_uri = uri


def parse_domjobinfo(stdout: str) -> dict[str, Any]:
    """``virsh domjobinfo`` → dict normalizado (claves snake_case).

    Valores con unidad se convierten: tiempos → ms, datos → MiB,
    velocidades → MiB/s; contadores quedan como int.
    """
    metrics: dict[str, Any] = {}
    unit_to_mib = {"b": 1 / (1024 * 1024), "kib": 1 / 1024, "mib": 1.0, "gib": 1024.0, "tib": 1024.0 * 1024}
    for line in stdout.splitlines():
        if ":" not in line:
            continue
        raw_key, _, raw_value = line.partition(":")
        key = re.sub(r"[^a-z0-9]+", "_", raw_key.strip().lower()).strip("_")
        value = raw_value.strip()
        if not key or not value:
            continue
        match = re.fullmatch(r"([0-9.]+)\s*([A-Za-z/]+)?", value)
        if not match:
            metrics[key] = value
            continue
        number = float(match.group(1))
        unit = (match.group(2) or "").lower()
        if unit in {"ms", "milliseconds"}:
            metrics[f"{key}_ms"] = number
        elif unit in {"s", "seconds"}:
            metrics[f"{key}_ms"] = number * 1000
        elif unit.rstrip("/s") in unit_to_mib and unit.endswith("/s"):
            metrics[f"{key}_mibps"] = number * unit_to_mib[unit.rstrip("/s")]
        elif unit in unit_to_mib:
            metrics[f"{key}_mib"] = number * unit_to_mib[unit]
        elif unit in {"pages/s", "pages"}:
            metrics[key] = number
        else:
            metrics[key] = number if not unit else value
    return metrics


def estimate_downtime_ms(ram_mib: float, dirty_rate_mibps: float, bandwidth_mibps: float) -> float | None:
    """Previsión grosera de downtime: working set restante / ancho de banda.

    Solo orientativa para el preflight; el downtime real se mide al acabar.
    """
    if bandwidth_mibps <= 0:
        return None
    if dirty_rate_mibps >= bandwidth_mibps:
        return None  # no converge sin auto-converge/postcopy
    working_set = max(64.0, min(ram_mib * 0.05, 1024.0))
    return round(1000.0 * working_set / bandwidth_mibps, 1)


class LiveMigrator:
    """Construye y ejecuta la máquina de estados (TD-4) de una live migration."""

    def __init__(self, backend: Any, plan: LiveMigrationPlan, *, channel: ProgressChannel | None = None,
                 journal: Any | None = None) -> None:
        self.backend = backend
        self.plan = plan
        self.channel = channel
        self._migrate_thread: threading.Thread | None = None
        self._migrate_result: dict[str, Any] = {}
        if journal is None:
            from ..migration_journal import MigrationJournal

            journal = MigrationJournal()
        self.journal = journal
        self.engine = MigrationEngine(self._build_phases(), channel=channel, kind="live-migration")

    # virsh helpers ---------------------------------------------------------- #

    def _virsh(self, args: list[str], *, check: bool = True, timeout: int = 120):
        return self.backend.virsh(args, check=check, timeout=timeout)

    def _target_virsh(self, args: list[str], *, check: bool = True, timeout: int = 60):
        return self.backend.run(
            ["virsh", "--connect", self.plan.target_uri, *args], check=check, timeout=timeout
        )

    # Fases ------------------------------------------------------------------ #

    def _build_phases(self) -> list[MigrationPhase]:
        return [
            MigrationPhase(name="preflight", run=self._run_preflight),
            MigrationPhase(name="transfer", run=self._run_prepare_target, rollback=self._rollback_target),
            MigrationPhase(
                name="switchover",
                run=self._run_migrate,
                rollback=self._rollback_migrate,
                touches_source=True,
                weight=8.0,
            ),
            MigrationPhase(name="activate", run=self._run_activate, touches_source=True),
        ]

    def run(self) -> dict[str, Any]:
        result = self.engine.run({"plan": self.plan})
        payload = result.to_dict()
        payload["measured_downtime_ms"] = self._migrate_result.get("downtime_ms")
        payload["jobinfo_completed"] = self._migrate_result.get("completed", {})
        return payload

    def cancel(self) -> None:
        """Aborta la migración: ``virDomainAbortJob`` → origen corriendo."""
        self.engine.request_cancel()
        self._virsh(["domjobabort", self.plan.vm_name], check=False)

    # preflight --------------------------------------------------------------- #

    def _run_preflight(self, context: dict[str, Any]) -> None:
        report = context["report"]
        plan = self.plan
        errors: list[str] = []
        warnings: list[str] = list(plan.extra_warnings)

        report("Comprobando la VM de origen", fraction=0.1)
        state = self._virsh(["domstate", plan.vm_name], check=False)
        if state.returncode != 0:
            raise HyperGeryError(f"Source VM does not exist: {plan.vm_name}")
        if state.stdout.strip().lower() not in {"running", "en ejecución", "ejecutando"}:
            raise HyperGeryError(
                f"Live migration requires a RUNNING VM (state: {state.stdout.strip()}). "
                "Use the offline migration fallback for stopped VMs."
            )

        dumpxml = self._virsh(["dumpxml", plan.vm_name]).stdout
        root = ET.fromstring(dumpxml)
        # v1.7: una VM con GPU/PCI passthrough NO se puede live-migrar.
        if root.findall("./devices/hostdev"):
            raise HyperGeryError(
                f"{plan.vm_name} has a PCI/host device passthrough (<hostdev>) attached — "
                "live migration is impossible with passthrough devices. Detach it first."
            )
        cdroms = [
            disk for disk in root.findall("./devices/disk")
            if disk.attrib.get("device") == "cdrom" and disk.find("source") is not None
        ]
        if cdroms:
            warnings.append(
                "The VM has CD-ROM media attached from a local path; if the ISO is not present on the "
                "target the migration will fail. Consider ejecting it."
            )

        report("Comprobando conectividad y versiones del destino", fraction=0.3)
        target_version = self._target_virsh(["version"], check=False)
        if target_version.returncode != 0:
            raise HyperGeryError(
                f"Cannot reach target hypervisor {plan.target_uri}: "
                f"{target_version.stderr.strip() or target_version.stdout.strip()}"
            )
        source_host = self._virsh(["hostname"], check=False).stdout.strip()
        target_host = self._target_virsh(["hostname"], check=False).stdout.strip()
        if source_host and source_host == target_host:
            raise HyperGeryError(f"Source and target are the same host ({source_host}).")

        report("Comprobando duplicados y recursos en el destino", fraction=0.5)
        existing = self._target_virsh(["dominfo", plan.vm_name], check=False)
        if existing.returncode == 0:
            raise HyperGeryError(f"A VM named {plan.vm_name} already exists on the target host.")

        ram_mib = 0.0
        dominfo = self._virsh(["dominfo", plan.vm_name], check=False).stdout
        match = re.search(r"(?:Max memory|Memoria máx[^:]*):\s+(\d+)\s*KiB", dominfo, re.IGNORECASE)
        if match:
            ram_mib = int(match.group(1)) / 1024.0
        free_output = self._target_virsh(["nodememstats"], check=False).stdout
        free_match = re.search(r"free\s*:\s*(\d+)\s*KiB", free_output, re.IGNORECASE)
        if free_match and ram_mib:
            target_free_mib = int(free_match.group(1)) / 1024.0
            if target_free_mib < ram_mib:
                errors.append(
                    f"Target host has {target_free_mib:.0f} MiB free but the VM needs {ram_mib:.0f} MiB."
                )

        report("Comprobando compatibilidad de CPU", fraction=0.7)
        cpu_xml = ET.tostring(root.find("./cpu"), encoding="unicode") if root.find("./cpu") is not None else ""
        if cpu_xml and "host-passthrough" in cpu_xml:
            warnings.append(
                "Esta VM usa la CPU real del equipo (host-passthrough): la migración en vivo "
                "SOLO funcionará entre equipos con CPU del mismo fabricante. Si el origen es AMD "
                "y el destino Intel (o al revés), fallará. Para migrar en caliente entre equipos "
                "distintos, recrea la VM marcando «preparar para migración en vivo» (CPU compatible)."
            )

        report("Decidiendo estrategia de almacenamiento", fraction=0.85)
        disk_paths = [
            source.attrib.get("file", "")
            for source in root.findall("./devices/disk/source")
            if source.attrib.get("file")
        ]
        shared = plan.shared_storage
        if shared is None:
            # Heurística: rutas bajo monturas de red típicas → shared.
            shared = bool(disk_paths) and all(
                any(token in path for token in ("/mnt/", "/nfs", "/nas", "/share"))
                for path in disk_paths
            )
            warnings.append(
                f"Storage strategy auto-detected as {'shared' if shared else 'block migration'} — "
                "override with shared_storage=True/False if wrong."
            )
        if shared:
            # UAT U10 (2026-06-10): el handoff del write-lock de imágenes de
            # QEMU no es fiable sobre SMB (durable handles) — el destino no
            # puede reanudar y el origen queda pausado. NFS sí está soportado.
            for path in disk_paths:
                fstype = disk_filesystem_type(path)
                if fstype in UNSUPPORTED_SHARED_STORAGE_FSTYPES:
                    raise HyperGeryError(
                        f"El disco {path} está en un filesystem {fstype}: CIFS/SMB no está "
                        "soportado para live migration shared-storage por el locking de "
                        "imágenes de QEMU; usa NFS o block migration (--block-migration)."
                    )
        context["shared_storage"] = shared

        estimate = estimate_downtime_ms(ram_mib, dirty_rate_mibps=64.0, bandwidth_mibps=float(plan.bandwidth_mibps or 1024))
        metrics = {"ram_mib": ram_mib, "shared_storage": shared}
        if estimate is not None:
            metrics["estimated_downtime_ms"] = estimate
        report("Preflight completado", fraction=1.0, metrics=metrics)
        context["preflight_warnings"] = warnings
        if errors:
            raise HyperGeryError("Live migration preflight failed: " + "; ".join(errors))

    # transfer (preparación del destino; NO toca el origen) ------------------- #

    def _run_prepare_target(self, context: dict[str, Any]) -> None:
        report = context["report"]
        if context.get("shared_storage"):
            report("Almacenamiento compartido: no hay que preparar discos", fraction=1.0)
            return
        report(
            "Block migration: los discos se copiarán por el canal de migración (--copy-storage-*)",
            fraction=1.0,
        )

    def _rollback_target(self, context: dict[str, Any]) -> None:
        # Nada que deshacer: la preparación no crea estado persistente.
        return

    # switchover (virsh migrate = pre-copy + pausa breve + reanudar) ----------- #

    def _migrate_args(self, context: dict[str, Any]) -> list[str]:
        plan = self.plan
        args = [
            "migrate",
            "--live",
            "--persistent",
            "--abort-on-error",
            "--verbose",
        ]
        if not context.get("shared_storage"):
            args.append("--copy-storage-inc" if plan.incremental_storage else "--copy-storage-all")
        if plan.auto_converge:
            args.append("--auto-converge")
        if plan.postcopy:
            args.extend(["--postcopy", "--postcopy-after-precopy"])
        if plan.bandwidth_mibps:
            args.extend(["--bandwidth", str(plan.bandwidth_mibps)])
        args.extend([plan.vm_name, plan.target_uri])
        return args

    def _run_migrate(self, context: dict[str, Any]) -> None:
        report = context["report"]
        plan = self.plan
        args = self._migrate_args(context)
        outcome: dict[str, Any] = {}
        # HG-BUG-0028: punto de no retorno. A partir de aquí, si el proceso
        # muere el origen queda parado pero arrancable: el journal persistente
        # impide arrancarlo a mano hasta confirmar/limpiar la migración.
        self.journal.begin(
            plan.vm_name,
            target_uri=plan.target_uri,
            operation_id=str(context.get("operation_id") or ""),
        )

        def migrate_worker() -> None:
            try:
                result = self._virsh(args, check=False, timeout=plan.timeout_seconds)
                outcome["returncode"] = result.returncode
                outcome["stderr"] = result.stderr
            except Exception as exc:  # noqa: BLE001 — propagado abajo
                outcome["returncode"] = -1
                outcome["stderr"] = str(exc)

        worker = threading.Thread(target=migrate_worker, daemon=True)
        worker.start()
        iterations_seen = 0
        while worker.is_alive():
            worker.join(timeout=JOBINFO_POLL_SECONDS)
            if not worker.is_alive():
                break
            if context["cancelled"]():
                self._virsh(["domjobabort", plan.vm_name], check=False)
            job = self._virsh(["domjobinfo", plan.vm_name], check=False)
            if job.returncode != 0:
                continue
            metrics = parse_domjobinfo(job.stdout)
            total = metrics.get("data_total_mib") or metrics.get("memory_total_mib") or 0
            processed = metrics.get("data_processed_mib") or metrics.get("memory_processed_mib") or 0
            fraction = min(0.99, processed / total) if total else 0.0
            iterations_seen = int(metrics.get("iteration", iterations_seen) or iterations_seen)
            speed = metrics.get("memory_bandwidth_mibps") or metrics.get("data_processed_mibps")
            remaining = metrics.get("data_remaining_mib") or metrics.get("memory_remaining_mib")
            eta = round(remaining / speed, 1) if speed and remaining else None
            live = {k: v for k, v in metrics.items() if isinstance(v, (int, float))}
            live["iterations"] = iterations_seen
            if eta is not None:
                live["eta_seconds"] = eta
            report(
                f"Pre-copy: {processed:.0f}/{total:.0f} MiB (iteración {iterations_seen})" if total else "Migrando…",
                fraction=fraction,
                metrics=live,
            )
        worker.join()
        if outcome.get("returncode") != 0:
            stderr = str(outcome.get("stderr") or "").strip()
            raise HyperGeryError(f"virsh migrate failed: {stderr or 'unknown error'}")
        completed = self._virsh(["domjobinfo", plan.vm_name, "--completed"], check=False)
        if completed.returncode == 0:
            stats = parse_domjobinfo(completed.stdout)
            self._migrate_result["completed"] = stats
            downtime = stats.get("total_downtime_ms")
            if downtime is not None:
                self._migrate_result["downtime_ms"] = downtime
                report(f"Switchover completado: downtime medido {downtime:.0f} ms", fraction=1.0, metrics={"downtime_ms": downtime})

    def _rollback_migrate(self, context: dict[str, Any]) -> None:
        """Tras un fallo/cancelación: origen corriendo, destino limpio."""
        plan = self.plan
        self._virsh(["domjobabort", plan.vm_name], check=False)
        source_state = self._virsh(["domstate", plan.vm_name], check=False).stdout.strip().lower()
        target_state = self._target_virsh(["domstate", plan.vm_name], check=False)
        target_running = target_state.returncode == 0 and "running" in target_state.stdout.lower()
        source_running = "running" in source_state or "ejecu" in source_state
        if target_state.returncode == 0 and not (target_running and not source_running):
            # Restos en el destino (definida o pausada) con el origen vivo →
            # nunca activa en dos hosts: limpiar el destino.
            self._target_virsh(["destroy", plan.vm_name], check=False)
            self._target_virsh(["undefine", plan.vm_name, "--nvram"], check=False)
        # HG-BUG-0028: solo se libera el journal si el origen ha vuelto a ser
        # la copia viva. Si el destino quedó promovido (origen parado), la
        # entrada permanece para que start_vm siga rechazando el origen.
        if source_running:
            self.journal.clear(plan.vm_name)

    # activate (confirmar destino y SOLO entonces limpiar el origen) ----------- #

    def _run_activate(self, context: dict[str, Any]) -> None:
        report = context["report"]
        plan = self.plan
        report("Confirmando el destino", fraction=0.3)
        deadline = time.monotonic() + 60
        target_running = False
        while time.monotonic() < deadline:
            state = self._target_virsh(["domstate", plan.vm_name], check=False)
            if state.returncode == 0 and "running" in state.stdout.lower():
                target_running = True
                break
            time.sleep(2)
        if not target_running:
            raise HyperGeryError(
                f"Target VM {plan.vm_name} is not running on {plan.target_uri} after migration — source kept."
            )
        source_state = self._virsh(["domstate", plan.vm_name], check=False)
        if source_state.returncode == 0 and "running" in source_state.stdout.lower():
            raise HyperGeryError(
                f"INVARIANT VIOLATION: {plan.vm_name} appears running on BOTH hosts; refusing to continue."
            )
        if plan.undefine_source_on_success and source_state.returncode == 0:
            report("Destino confirmado: limpiando la definición del origen", fraction=0.7)
            self._virsh(["undefine", plan.vm_name, "--nvram"], check=False)
            # HG-BUG-0028: el origen ya no existe → arrancarlo es imposible y
            # seguro liberar el journal.
            self.journal.clear(plan.vm_name)
        else:
            # Se conserva la definición del origen (--keep-source-definition):
            # con shared storage arrancarlo sigue siendo peligroso, así que la
            # entrada del journal permanece y debe limpiarse a mano
            # (hypergery-cli v1 migrate-journal clear <vm>).
            report(
                "VM activa en el destino. El origen se conserva: limpia el journal a mano para poder arrancarlo.",
                fraction=0.9,
            )
        report("VM activa en el destino", fraction=1.0)
