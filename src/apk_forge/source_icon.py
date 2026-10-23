from __future__ import annotations

import zipfile
from pathlib import Path

ICON_NAMES = ("icon.png", "icon.webp", "icon.jpg", "icon.jpeg")


def extract_source_icon(source_package: Path, app_id: str, output_dir: Path) -> Path | None:
    """Extract an icon image shipped as package metadata (common in APKM/XAPK)."""
    try:
        with zipfile.ZipFile(source_package) as package:
            candidates = [
                name for name in package.namelist()
                if "/" not in name and name.lower() in ICON_NAMES
            ]
            if not candidates:
                return None
            selected = sorted(candidates, key=lambda name: ICON_NAMES.index(name.lower()))[0]
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"{app_id}-icon{Path(selected).suffix.lower()}"
            output_path.write_bytes(package.read(selected))
            return output_path
    except (OSError, zipfile.BadZipFile):
        return None
