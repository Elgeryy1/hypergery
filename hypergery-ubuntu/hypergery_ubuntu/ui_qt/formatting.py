"""Pure-Python formatting helpers shared by the CLI and the Qt UI.

This module intentionally has NO PySide6 (or any Qt) import so it can be unit
tested everywhere and reused from the CLI without pulling in a GUI toolkit.
"""

from __future__ import annotations


def format_size(num_bytes: int | float | None) -> str:
    """Return a human-readable size string (B/KiB/MiB/GiB/TiB).

    ``None`` (and any falsy value) is treated as ``0`` so the result is the
    sensible placeholder ``"0 B"`` — matching how ``cli.py`` already calls this
    helper (callers always pass ``.get(..., 0)`` / ``... or 0``).

    Examples:
        >>> format_size(None)
        '0 B'
        >>> format_size(0)
        '0 B'
        >>> format_size(4096)
        '4.0 KiB'
    """
    size = float(num_bytes or 0)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{int(size)} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{int(size)} B"


def format_mib(value: int | None) -> str:
    """Return ``"<value> MiB"`` or the placeholder ``"desconocido"``.

    ``None`` and ``0`` both yield ``"desconocido"`` — identical semantics to the
    original ``styles.format_mib``.

    Examples:
        >>> format_mib(2048)
        '2048 MiB'
        >>> format_mib(None)
        'desconocido'
        >>> format_mib(0)
        'desconocido'
    """
    return f"{value} MiB" if value else "desconocido"


# Ordered so that the most specific / least ambiguous matches win first.
# Each entry is (icon_key, tuple of case-insensitive substrings to look for).
_OS_ICON_MATCHERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("windows", ("windows", "win", "msdos")),
    ("ubuntu", ("ubuntu",)),
    ("debian", ("debian",)),
    ("fedora", ("fedora",)),
    ("centos", ("centos", "rhel", "redhat", "red hat", "rocky", "alma")),
    ("arch", ("archlinux", "arch", "manjaro")),
    ("linux", ("linux", "gnu", "kernel")),
)


def os_icon_key(name: str | None, os_hint: str | None = None) -> str:
    """Map a VM/template name and optional OS string to an icon key.

    Returns one of: ``"ubuntu"``, ``"debian"``, ``"fedora"``, ``"centos"``,
    ``"arch"``, ``"windows"``, ``"linux"`` or ``"generic"`` (the fallback for
    anything unrecognised). Matching is case-insensitive substring matching over
    the combined ``name`` and ``os_hint`` text.

    Examples:
        >>> os_icon_key("ubuntu-srv")
        'ubuntu'
        >>> os_icon_key("win11")
        'windows'
        >>> os_icon_key("my-box", "Debian GNU/Linux")
        'debian'
        >>> os_icon_key("mystery")
        'generic'
    """
    haystack = " ".join(part for part in (name, os_hint) if part).lower()
    if not haystack:
        return "generic"
    for icon_key, needles in _OS_ICON_MATCHERS:
        if any(needle in haystack for needle in needles):
            return icon_key
    return "generic"
