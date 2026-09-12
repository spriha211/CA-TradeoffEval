from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Iterable


MEASURES = tuple(f"M{i:02d}" for i in range(2, 12))
EXPECTED_COMPONENTS = {
    "M02": 65, "M03": 58, "M04": 12, "M05": 64, "M06": 29,
    "M07": 22, "M08": 28, "M09": 25, "M10": 31, "M11": 33,
}
BLIND_ID_RE = re.compile(r"^(M(?:0[2-9]|1[01]))-B(\d{3})$")
DENIED_NAME_PARTS = ("mapping", "unblind", "condition_map", "condition-to")


class IntegrityError(RuntimeError):
    pass


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def reject_mapping_path(path: Path) -> None:
    """Fail closed on private mapping directories and mapping-like filenames."""
    resolved = _resolved(path)
    lowered = str(resolved).lower()
    if "runs/scored/private_mappings" in lowered:
        raise IntegrityError(f"Forbidden private-mapping path: {path}")
    allowed_audit_suffixes = (
        "/runs/audits/model_assisted_scoring/pre_unblind_integrity_manifest.json",
        "/runs/audits/model_assisted_scoring/pre_unblind_analysis_amendment.json",
    )
    if lowered.endswith(allowed_audit_suffixes):
        return
    if any(part in resolved.name.lower() for part in DENIED_NAME_PARTS):
        raise IntegrityError(f"Forbidden mapping-like filename: {path.name}")


def authorize_read(root: Path, path: Path) -> Path:
    root = _resolved(root)
    path = _resolved(path)
    reject_mapping_path(path)

    allowed = path == root / "data/reference_inventories/SCORING_GUIDE.md"
    allowed = allowed or bool(
        re.fullmatch(r"M(?:0[2-9]|1[01])_components\.csv", path.name)
        and path.parent == root / "data/reference_inventories"
    )
    allowed = allowed or (
        _is_within(path, root / "runs/blinded")
        and bool(re.fullmatch(r"M(?:0[2-9]|1[01])-B\d{3}\.txt", path.name))
    )
    allowed = allowed or any(
        _is_within(path, root / rel)
        for rel in (
            "analysis/model_assisted_scoring",
            "results",
            "runs/audits/model_assisted_scoring",
        )
    )
    if not allowed:
        raise IntegrityError(f"Read is outside the scoring allowlist: {path}")
    if not path.is_file():
        raise IntegrityError(f"Required input is not a file: {path}")
    return path


def authorize_write(root: Path, path: Path) -> Path:
    root = _resolved(root)
    path = _resolved(path)
    reject_mapping_path(path)
    allowed = any(
        _is_within(path, root / rel)
        for rel in (
            "analysis/model_assisted_scoring",
            "results",
            "runs/audits/model_assisted_scoring",
        )
    )
    if not allowed:
        raise IntegrityError(f"Write is outside the scoring allowlist: {path}")
    return path


def read_text(root: Path, path: Path) -> str:
    return authorize_read(root, path).read_text(encoding="utf-8")


def read_bytes(root: Path, path: Path) -> bytes:
    return authorize_read(root, path).read_bytes()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(root: Path, path: Path) -> str:
    return sha256_bytes(read_bytes(root, path))


def atomic_write_bytes(root: Path, path: Path, data: bytes) -> None:
    path = authorize_write(root, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite existing file: {path}")
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        # Link is atomic and fails if the destination appeared concurrently.
        os.link(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def atomic_write_text(root: Path, path: Path, text: str) -> None:
    atomic_write_bytes(root, path, text.encode("utf-8"))


def atomic_write_json(root: Path, path: Path, value: Any) -> None:
    atomic_write_text(root, path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def append_jsonl(root: Path, path: Path, value: Any) -> None:
    path = authorize_write(root, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def append_jsonl_batch(root: Path, path: Path, values: Iterable[Any]) -> None:
    """Append a prevalidated event batch with one flush, or atomically create a new log."""
    path = authorize_write(root, path)
    values = list(values)
    if not values:
        raise IntegrityError("Refusing to append an empty JSONL batch")
    text = "".join(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
        for value in values
    )
    if not path.exists():
        atomic_write_text(root, path, text)
        return
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())


def validate_measure(measure: str) -> str:
    measure = measure.upper()
    if measure not in MEASURES:
        raise IntegrityError(f"Measure must be one of {', '.join(MEASURES)}")
    return measure


def validate_blind_id(blind_id: str, measure: str | None = None) -> str:
    match = BLIND_ID_RE.fullmatch(blind_id)
    if not match or (measure and match.group(1) != measure):
        raise IntegrityError(f"Invalid blind ID: {blind_id}")
    return blind_id


def require_unique(values: Iterable[str], label: str) -> None:
    values = list(values)
    if len(values) != len(set(values)):
        raise IntegrityError(f"Duplicate {label} values detected")
