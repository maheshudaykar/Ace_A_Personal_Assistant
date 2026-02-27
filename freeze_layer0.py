"""Generate SHA256 checksums for Phase 1 Layer 0 (immutable kernel)."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path


def compute_file_hash(file_path: Path) -> str:
    """Compute SHA256 hash of a file."""
    hasher = sha256()
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def freeze_layer0_checksums() -> dict[str, str]:
    """Compute checksums for all Layer 0 (kernel) files."""
    kernel_dir = Path("ace/ace_kernel")
    checksums = {}
    
    if not kernel_dir.exists():
        raise FileNotFoundError(f"Kernel directory not found: {kernel_dir}")
    
    for py_file in sorted(kernel_dir.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        checksums[str(py_file)] = compute_file_hash(py_file)
    
    return checksums


if __name__ == "__main__":
    print("Computing Phase 1 Layer 0 checksums...")
    checksums = freeze_layer0_checksums()
    
    snapshot = {
        "phase": "1",
        "tag": "ace_phase1_stable",
        "layer": "0_immutable_kernel",
        "checksums": checksums,
    }
    
    output_path = Path("phase1_layer0_checksums.json")
    with output_path.open("w") as f:
        json.dump(snapshot, f, indent=2)
    
    print(f"✅ Layer 0 checksums saved to {output_path}")
    for file, checksum in checksums.items():
        print(f"   {file}: {checksum[:16]}...")
