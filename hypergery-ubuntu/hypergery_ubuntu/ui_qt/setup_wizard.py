"""First Run Setup Wizard (v1.5): asistente Qt de primera ejecución.

Capa fina sobre `hypergery_ubuntu.firstrun` (toda la lógica es testeable sin
Qt). Reglas duras:
- NUNCA arranca Docker sin una confirmación explícita del usuario.
- NUNCA ejecuta sudo: los comandos que falten se muestran como texto.
- El token jamás se muestra en logs; en pantalla va en un campo de password.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from .. import APP_NAME, __version__
from .. import firstrun


def _info_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    return label


class WelcomePage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle(f"Bienvenido a {APP_NAME} {__version__}")
        layout = QVBoxLayout(self)
        layout.addWidget(
            _info_label(
                "Este asistente prepara HyperGery en unos pocos pasos: cómo vas a "
                "usarlo, dónde guardar las máquinas, y la conexión con el Hub si "
                "usas varios equipos.\n\nNo se cambia nada del sistema sin "
                "preguntarte, y puedes volver a lanzarlo cuando quieras con "
                "«hypergery --first-run»."
            )
        )


class ProfilePage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("¿Cómo vas a usar HyperGery?")
        layout = QVBoxLayout(self)
        self.group = QButtonGroup(self)
        self.buttons: dict[str, QRadioButton] = {}
        for key, label in firstrun.SETUP_PROFILES.items():
            button = QRadioButton(label)
            self.group.addButton(button)
            self.buttons[key] = button
            layout.addWidget(button)
        self.buttons["solo"].setChecked(True)
        layout.addStretch()

    def selected_profile(self) -> str:
        for key, button in self.buttons.items():
            if button.isChecked():
                return key
        return "solo"


class HubPage(QWizardPage):
    """Docker/Hub según el perfil: genera bundle, prueba conexión.

    El botón «Arrancar Hub ahora» SOLO existe para el perfil local y pide
    confirmación explícita antes de ejecutar docker compose.
    """

    def __init__(self, wizard: "SetupWizard") -> None:
        super().__init__()
        self._wizard = wizard
        self.setTitle("Hub y Docker")
        layout = QVBoxLayout(self)
        self.context_label = _info_label("")
        layout.addWidget(self.context_label)

        self.bundle_button = QPushButton("Generar carpeta Docker del Hub")
        self.bundle_button.clicked.connect(self._generate_bundle)
        layout.addWidget(self.bundle_button)

        self.start_button = QPushButton("Arrancar Hub ahora (docker compose up -d)…")
        self.start_button.clicked.connect(self._start_local_hub)
        layout.addWidget(self.start_button)

        url_row = QHBoxLayout()
        url_row.addWidget(QLabel("URL del Hub:"))
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("http://IP-del-NAS:8765")
        url_row.addWidget(self.url_edit)
        layout.addLayout(url_row)

        token_row = QHBoxLayout()
        token_row.addWidget(QLabel("Token:"))
        self.token_edit = QLineEdit()
        self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_edit.setPlaceholderText("token de pairing (secreto)")
        token_row.addWidget(self.token_edit)
        layout.addLayout(token_row)

        self.test_button = QPushButton("Probar conexión")
        self.test_button.clicked.connect(self._test_connection)
        layout.addWidget(self.test_button)

        self.status_label = _info_label("")
        layout.addWidget(self.status_label)
        layout.addStretch()
        self._bundle_dir: Path | None = None

    def initializePage(self) -> None:  # noqa: N802 (API Qt)
        profile = self._wizard.profile_page.selected_profile()
        needs_hub = profile in {"local-docker", "nas-docker", "client"}
        self.bundle_button.setVisible(profile in {"local-docker", "nas-docker"})
        self.start_button.setVisible(profile == "local-docker")
        for widget in (self.url_edit, self.token_edit, self.test_button):
            widget.setEnabled(needs_hub)
        if profile == "solo":
            self.context_label.setText("Modo «solo este PC»: no necesitas Hub ni Docker. Pulsa Siguiente.")
            return
        docker = firstrun.detect_docker()
        if profile == "local-docker":
            self.context_label.setText(
                f"Docker: {docker['detail'] or ('disponible' if docker['docker_available'] else 'no disponible')}\n"
                "Genera la configuración local del Hub. NO se arranca nada sin tu confirmación."
            )
        elif profile == "nas-docker":
            self.context_label.setText(
                "Genera la carpeta exportable, cópiala al NAS/equipo dedicado y sigue su "
                "README_SETUP.md. Después pega aquí la URL y el token y prueba la conexión."
            )
        else:
            self.context_label.setText("Pega la URL y el token del Hub existente (pídeselos al propietario: «hypergery-cli hub pairing-info»).")

    def _generate_bundle(self) -> None:
        profile = self._wizard.profile_page.selected_profile()
        if profile == "local-docker":
            default_dir = Path.home() / ".config" / "hypergery" / "hub-docker"
        else:
            default_dir = Path.cwd() / "dist" / "hypergery-hub-docker"
        chosen = QFileDialog.getExistingDirectory(self, "Carpeta destino del bundle", str(default_dir.parent))
        dest = Path(chosen) / default_dir.name if chosen else default_dir
        try:
            firstrun.generate_docker_bundle(dest)
        except OSError as exc:
            self.status_label.setText(f"No se pudo generar el bundle: {exc}")
            return
        self._bundle_dir = dest
        self.status_label.setText(
            f"Bundle generado en {dest}.\nSiguiente paso: copia .env.example a .env y define el token "
            "(el fichero README_SETUP.md lo explica paso a paso)."
        )

    def _start_local_hub(self) -> None:
        if self._bundle_dir is None or not (self._bundle_dir / "docker-compose.yml").exists():
            self.status_label.setText("Primero genera la carpeta Docker del Hub.")
            return
        answer = QMessageBox.question(
            self,
            "Arrancar el Hub",
            f"Se va a ejecutar:\n\n  docker compose up -d\n\nen {self._bundle_dir}.\n\n¿Continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            self.status_label.setText("Arranque cancelado: no se ha ejecutado nada.")
            return
        try:
            proc = subprocess.run(
                ["docker", "compose", "up", "-d"],
                cwd=self._bundle_dir,
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.status_label.setText(f"No se pudo ejecutar docker compose: {exc}")
            return
        if proc.returncode == 0:
            self.url_edit.setText(self.url_edit.text() or "http://127.0.0.1:8765")
            self.status_label.setText("Hub arrancado. Prueba la conexión con su token.")
        else:
            self.status_label.setText(f"docker compose falló:\n{(proc.stderr or proc.stdout).strip()[:500]}")

    def _test_connection(self) -> None:
        result = firstrun.test_hub_connection(self.url_edit.text(), self.token_edit.text())
        self.status_label.setText(result["message"])
        self._wizard.hub_test_status = result["status"]


class StoragePage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("¿Dónde guardamos las máquinas?")
        layout = QVBoxLayout(self)
        layout.addWidget(_info_label("Por defecto: ~/.local/share/hypergery/vms. Puedes elegir otra carpeta o un montaje del NAS. No se borra nada."))
        row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("(vacío = ruta por defecto)")
        row.addWidget(self.path_edit)
        browse = QPushButton("Elegir…")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        layout.addLayout(row)
        self.check_button = QPushButton("Comprobar permisos y espacio")
        self.check_button.clicked.connect(self._check)
        layout.addWidget(self.check_button)
        self.status_label = _info_label("")
        layout.addWidget(self.status_label)
        layout.addStretch()

    def _browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Carpeta para las máquinas")
        if chosen:
            self.path_edit.setText(chosen)

    def _check(self) -> None:
        path = self.path_edit.text().strip() or str(Path.home() / ".local" / "share" / "hypergery" / "vms")
        info = firstrun.check_storage_path(path)
        pieces = [info["detail"] or "Ruta utilizable."]
        if info["free_mib"]:
            pieces.append(f"Espacio libre: {info['free_mib'] / 1024:.1f} GiB.")
        self.status_label.setText(" ".join(pieces))


class LibvirtPage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Virtualización (KVM/libvirt)")
        layout = QVBoxLayout(self)
        self.status_label = _info_label("")
        layout.addWidget(self.status_label)
        self.commands_label = QLabel("")
        self.commands_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.commands_label.setWordWrap(True)
        layout.addWidget(self.commands_label)
        layout.addStretch()

    def initializePage(self) -> None:  # noqa: N802 (API Qt)
        info = firstrun.detect_libvirt()
        lines = [
            f"virsh: {'✓ instalado' if info['virsh_available'] else '✗ no encontrado'}",
            f"qemu:///system: {'✓ responde' if info['system_uri_ok'] else '✗ no responde'}",
            f"grupo libvirt: {'✓' if info['in_libvirt_group'] else '✗'} · grupo kvm: {'✓' if info['in_kvm_group'] else '✗'}",
            info["detail"],
        ]
        self.status_label.setText("\n".join(filter(None, lines)))
        if info["suggested_commands"]:
            self.commands_label.setText(
                "Para arreglarlo, ejecuta TÚ estos comandos en una terminal (el asistente nunca usa sudo):\n\n"
                + "\n".join(f"  {command}" for command in info["suggested_commands"])
            )
        else:
            self.commands_label.setText("Todo listo: no hace falta ningún comando.")


class SecurityPage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Seguridad (así funciona HyperGery)")
        layout = QVBoxLayout(self)
        layout.addWidget(
            _info_label(
                "• El Hub y el API exigen token SIEMPRE; el token se guarda con permisos 0600.\n"
                "• Nada se expone a Internet: fuera de tu LAN, usa VPN (WireGuard/Tailscale) o TLS.\n"
                "• Las migraciones solo viajan por qemu+ssh o qemu+tls (qemu+tcp está prohibido).\n"
                "• Los invitados tienen permisos limitados y nunca acciones destructivas.\n"
                "• Todo lo destructivo (borrar, apagar a la fuerza, migrar) pide confirmación.\n\n"
                "Política completa: docs/security/CONNECTIVITY_POLICY.md"
            )
        )


class SummaryPage(QWizardPage):
    def __init__(self, wizard: "SetupWizard") -> None:
        super().__init__()
        self._wizard = wizard
        self.setTitle("Resumen")
        layout = QVBoxLayout(self)
        self.summary_label = _info_label("")
        layout.addWidget(self.summary_label)
        export_button = QPushButton("Exportar informe…")
        export_button.clicked.connect(self._export)
        layout.addWidget(export_button)
        layout.addWidget(_info_label("Al pulsar Finalizar se guarda la configuración (0600) y se abre la aplicación."))
        layout.addStretch()

    def _report(self) -> dict:
        wizard = self._wizard
        return {
            "profile": wizard.profile_page.selected_profile(),
            "hub_url": wizard.hub_page.url_edit.text().strip() or "(sin Hub)",
            "hub_token_present": bool(wizard.hub_page.token_edit.text()),
            "hub_test_status": wizard.hub_test_status or "(sin probar)",
            "storage_path": wizard.storage_page.path_edit.text().strip() or "(por defecto)",
            "libvirt": firstrun.detect_libvirt(),
            "docker": firstrun.detect_docker(),
        }

    def initializePage(self) -> None:  # noqa: N802 (API Qt)
        report = self._report()
        self.summary_label.setText(
            f"Modo: {firstrun.SETUP_PROFILES[report['profile']]}\n"
            f"Hub: {report['hub_url']} · token: {'definido' if report['hub_token_present'] else 'no definido'} · prueba: {report['hub_test_status']}\n"
            f"Almacenamiento: {report['storage_path']}\n"
            f"libvirt: {'OK' if report['libvirt']['system_uri_ok'] else 'pendiente (ver paso anterior)'}\n"
            f"Docker: {'OK' if report['docker']['docker_available'] else 'no disponible'}"
        )

    def _export(self) -> None:
        target, _filter = QFileDialog.getSaveFileName(self, "Guardar informe", "hypergery-setup-report.json", "JSON (*.json)")
        if not target:
            return
        # El informe nunca incluye el token, solo si está definido.
        Path(target).write_text(json.dumps(self._report(), indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


class SetupWizard(QWizard):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} — Primera ejecución")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.hub_test_status = ""
        self.welcome_page = WelcomePage()
        self.profile_page = ProfilePage()
        self.hub_page = HubPage(self)
        self.storage_page = StoragePage()
        self.libvirt_page = LibvirtPage()
        self.security_page = SecurityPage()
        self.summary_page = SummaryPage(self)
        for page in (
            self.welcome_page,
            self.profile_page,
            self.hub_page,
            self.storage_page,
            self.libvirt_page,
            self.security_page,
            self.summary_page,
        ):
            self.addPage(page)

    def accept(self) -> None:  # Finalizar
        firstrun.mark_first_run_complete(
            self.profile_page.selected_profile(),
            hub_url=self.hub_page.url_edit.text().strip(),
            hub_token=self.hub_page.token_edit.text().strip(),
            storage_path=self.storage_page.path_edit.text().strip(),
        )
        super().accept()


def run_setup_wizard(parent=None) -> bool:
    """Muestra el asistente modal. True si el usuario lo completó."""
    wizard = SetupWizard(parent)
    return wizard.exec() == QWizard.DialogCode.Accepted


def maybe_run_setup_wizard(*, force: bool = False, parent=None) -> bool:
    """Lanza el asistente si toca (primera ejecución o force). Devuelve True
    si se mostró y completó; False si no se mostró o se canceló."""
    if not force and not firstrun.should_show_wizard():
        return False
    return run_setup_wizard(parent)
