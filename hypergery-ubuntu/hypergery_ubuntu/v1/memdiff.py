from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import MemDiffError
from .hglog import get_logger, now_iso

DEFAULT_BLOCK_SIZE = 64 * 1024

__all__ = [
    "DEFAULT_BLOCK_SIZE",
    "MemDiffSnapshot",
    "MemDiffDelta",
    "snapshot_state",
    "compare_snapshots",
    "produce_delta",
    "apply_delta",
    "verify_result",
    "save_delta",
    "load_delta",
]


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iter_blocks(path: Path, block_size: int):
    with path.open("rb") as handle:
        index = 0
        while True:
            block = handle.read(block_size)
            if not block:
                return
            yield index, block
            index += 1


@dataclass
class MemDiffSnapshot:
    """Block-level fingerprint of a serialized state file."""

    snapshot_id: str
    source: str
    size_bytes: int
    block_size: int
    block_hashes: list[str]
    full_hash: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "source": self.source,
            "size_bytes": self.size_bytes,
            "block_size": self.block_size,
            "block_hashes": self.block_hashes,
            "full_hash": self.full_hash,
            "created_at": self.created_at,
        }


@dataclass
class MemDiffDelta:
    """Changed blocks between a base snapshot and a target state."""

    base_id: str
    target_id: str
    block_size: int
    size_bytes: int
    changed_blocks: dict[int, bytes] = field(default_factory=dict)
    target_full_hash: str = ""
    created_at: str = ""

    @property
    def changed_count(self) -> int:
        return len(self.changed_blocks)

    def savings_estimate(self) -> dict[str, Any]:
        delta_bytes = sum(len(block) for block in self.changed_blocks.values())
        return {
            "full_size_bytes": self.size_bytes,
            "delta_size_bytes": delta_bytes,
            "saved_bytes": max(0, self.size_bytes - delta_bytes),
            "saved_percent": round(100.0 * max(0, self.size_bytes - delta_bytes) / self.size_bytes, 1)
            if self.size_bytes
            else 0.0,
            "changed_blocks": self.changed_count,
        }


def snapshot_state(path: str | Path, *, block_size: int = DEFAULT_BLOCK_SIZE) -> MemDiffSnapshot:
    source = Path(path).expanduser()
    if not source.is_file():
        raise MemDiffError(f"State file does not exist: {source}")
    if block_size <= 0:
        raise MemDiffError("block_size must be positive.")
    hashes = [hashlib.sha256(block).hexdigest() for _index, block in _iter_blocks(source, block_size)]
    return MemDiffSnapshot(
        snapshot_id=f"mds-{uuid.uuid4().hex[:12]}",
        source=str(source),
        size_bytes=source.stat().st_size,
        block_size=block_size,
        block_hashes=hashes,
        full_hash=_file_sha256(source),
        created_at=now_iso(),
    )


def compare_snapshots(base: MemDiffSnapshot, target: MemDiffSnapshot) -> dict[str, Any]:
    if base.block_size != target.block_size:
        raise MemDiffError(
            f"Cannot compare snapshots with different block sizes: {base.block_size} vs {target.block_size}"
        )
    changed = [
        index
        for index in range(max(len(base.block_hashes), len(target.block_hashes)))
        if index >= len(base.block_hashes)
        or index >= len(target.block_hashes)
        or base.block_hashes[index] != target.block_hashes[index]
    ]
    return {
        "base_id": base.snapshot_id,
        "target_id": target.snapshot_id,
        "total_blocks": len(target.block_hashes),
        "changed_blocks": changed,
        "unchanged_blocks": len(target.block_hashes) - sum(1 for index in changed if index < len(target.block_hashes)),
        "identical": not changed and base.size_bytes == target.size_bytes,
    }


def produce_delta(base: MemDiffSnapshot, target_path: str | Path) -> MemDiffDelta:
    target = Path(target_path).expanduser()
    target_snapshot = snapshot_state(target, block_size=base.block_size)
    comparison = compare_snapshots(base, target_snapshot)
    changed_blocks: dict[int, bytes] = {}
    wanted = set(comparison["changed_blocks"])
    for index, block in _iter_blocks(target, base.block_size):
        if index in wanted:
            changed_blocks[index] = block
    delta = MemDiffDelta(
        base_id=base.snapshot_id,
        target_id=target_snapshot.snapshot_id,
        block_size=base.block_size,
        size_bytes=target_snapshot.size_bytes,
        changed_blocks=changed_blocks,
        target_full_hash=target_snapshot.full_hash,
        created_at=now_iso(),
    )
    get_logger().info(
        "memdiff",
        f"delta produced: {delta.changed_count} changed block(s) of {len(target_snapshot.block_hashes)}",
        details=delta.savings_estimate(),
    )
    return delta


def apply_delta(base_path: str | Path, delta: MemDiffDelta, output_path: str | Path) -> Path:
    """base + delta → output. Verifies the result hash; raises on mismatch."""
    base = Path(base_path).expanduser()
    if not base.is_file():
        raise MemDiffError(f"Base state file does not exist: {base}")
    output = Path(output_path).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copyfile(base, output)
        with output.open("r+b") as handle:
            handle.truncate(delta.size_bytes)
            for index, block in sorted(delta.changed_blocks.items()):
                handle.seek(index * delta.block_size)
                handle.write(block)
    except OSError as exc:
        # Never leave a half-written file that looks like a result.
        output.unlink(missing_ok=True)
        raise MemDiffError(f"Failed to apply delta: {exc}") from exc
    if not verify_result(output, delta):
        output.unlink(missing_ok=True)
        raise MemDiffError("Applied delta does not match the target hash — refusing to keep the corrupt result.")
    return output


def verify_result(result_path: str | Path, delta: MemDiffDelta) -> bool:
    result = Path(result_path).expanduser()
    if not result.is_file():
        return False
    return _file_sha256(result) == delta.target_full_hash


# Persistence ------------------------------------------------------------------ #


def save_delta(delta: MemDiffDelta, directory: str | Path) -> Path:
    """Persist a delta: metadata in delta.json, raw blocks under blocks/."""
    target = Path(directory).expanduser()
    blocks_dir = target / "blocks"
    blocks_dir.mkdir(parents=True, exist_ok=True)
    for index, block in delta.changed_blocks.items():
        (blocks_dir / f"{index}.bin").write_bytes(block)
    metadata = {
        "base_id": delta.base_id,
        "target_id": delta.target_id,
        "block_size": delta.block_size,
        "size_bytes": delta.size_bytes,
        "changed_blocks": sorted(delta.changed_blocks),
        "target_full_hash": delta.target_full_hash,
        "created_at": delta.created_at,
        "block_hashes": {str(index): hashlib.sha256(block).hexdigest() for index, block in delta.changed_blocks.items()},
    }
    (target / "delta.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def load_delta(directory: str | Path) -> MemDiffDelta:
    source = Path(directory).expanduser()
    metadata_path = source / "delta.json"
    if not metadata_path.is_file():
        raise MemDiffError(f"Missing delta.json in {source}")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MemDiffError(f"Cannot read delta metadata: {exc}") from exc
    changed_blocks: dict[int, bytes] = {}
    for index in metadata.get("changed_blocks", []):
        block_path = source / "blocks" / f"{index}.bin"
        if not block_path.is_file():
            raise MemDiffError(f"Missing delta block file: {block_path}")
        block = block_path.read_bytes()
        expected = metadata.get("block_hashes", {}).get(str(index))
        if expected and hashlib.sha256(block).hexdigest() != expected:
            raise MemDiffError(f"Corrupt delta block: {block_path}")
        changed_blocks[int(index)] = block
    return MemDiffDelta(
        base_id=str(metadata.get("base_id") or ""),
        target_id=str(metadata.get("target_id") or ""),
        block_size=int(metadata.get("block_size") or DEFAULT_BLOCK_SIZE),
        size_bytes=int(metadata.get("size_bytes") or 0),
        changed_blocks=changed_blocks,
        target_full_hash=str(metadata.get("target_full_hash") or ""),
        created_at=str(metadata.get("created_at") or ""),
    )
