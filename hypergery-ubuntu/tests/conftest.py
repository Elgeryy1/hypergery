"""Configuración compartida de pytest (HG-BUG-0011: gate de libvirt real)."""

from __future__ import annotations

import os
import shutil

import pytest


def real_libvirt_available() -> bool:
    return shutil.which("virsh") is not None and os.environ.get("HYPERGERY_REAL_LIBVIRT") == "1"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if real_libvirt_available():
        return
    skip = pytest.mark.skip(
        reason="needs real libvirt: install virsh and run with HYPERGERY_REAL_LIBVIRT=1"
    )
    for item in items:
        if "needsRealLibvirt" in item.keywords:
            item.add_marker(skip)
