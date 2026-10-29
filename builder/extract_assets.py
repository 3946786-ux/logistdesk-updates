"""Extract embedded LogistDesk UI assets from the already-published 2.0.0 EXE.

The public build snapshot intentionally excludes historical/private Git objects.
Artwork is recovered from the previously published binary (same public repo).
"""
from __future__ import annotations
import sys
from pathlib import Path
from PyInstaller.archive.readers import CArchiveReader


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("Usage: extract_assets.py OLD_LOGISTDESK_EXE TARGET_ASSETS_DIR")
    exe = Path(sys.argv[1])
    target = Path(sys.argv[2])
    archive = CArchiveReader(str(exe))
    extracted = []
    for name in archive.toc:
        normalized = str(name).replace("\\", "/")
        if not normalized.startswith("assets/"):
            continue
        relative = Path(normalized).relative_to("assets")
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError("Unsafe asset path")
        if relative.suffix.lower() not in (".png", ".ico"):
            continue
        data = archive.extract(name)
        if not isinstance(data, bytes) or not data:
            raise RuntimeError("Cannot extract asset " + normalized)
        dst = target / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        extracted.append(relative.as_posix())
    required = {"logistdesk.ico", "logistdesk.png", "logistdesk_mark.png"}
    if not required.issubset(extracted):
        raise RuntimeError("Missing original LogistDesk assets: "
                           + str(sorted(required - set(extracted))))
    print("Restored", len(extracted), "original public release artwork files")


if __name__ == "__main__":
    main()
