"""HyperGery Ubuntu."""

# Única fuente de verdad de la versión (HG-BUG-0017).
# pyproject.toml la lee vía [tool.setuptools.dynamic] y la UI vía
# ui_qt.styles.APP_DISPLAY_VERSION.
__version__ = "1.7.0.dev0"

APP_NAME = "HyperGery"
APP_ID = "hypergery"
APP_HOMEPAGE = "https://github.com/Elgeryy1/hypergery"
APP_DESCRIPTION = "Gestor de máquinas virtuales KVM / QEMU / libvirt para Ubuntu"
