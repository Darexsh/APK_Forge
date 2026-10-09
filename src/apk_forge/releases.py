from __future__ import annotations

import re
from pathlib import Path

from apk_forge.models import ManagedApp

_VERSION_MARKERS = (
    re.compile(r"(?:^|[_\-\s])v(?P<version>\d+(?:[._-]\w+)*(?:\.build\d+)?)$", re.IGNORECASE),
    re.compile(r"(?:^|[_\-\s])(?P<version>\d+(?:[._-]\w+)*(?:\.build\d+)?)$", re.IGNORECASE),
)


def managed_release_tag(app: ManagedApp, version_name: str) -> str:
    return f"{app.output.release_prefix}-{version_name}"


def managed_asset_name(app: ManagedApp, version_name: str) -> str:
    if app.output.asset_name is not None:
        return app.output.asset_name
    return f"{app.id}-{version_name}-patched.apk"


def source_version_name(source_path: Path) -> str:
    stem = source_path.stem
    for pattern in _VERSION_MARKERS:
        match = pattern.search(stem)
        if match:
            return normalize_version_name(match.group("version"))
    return "unknown"


def source_version_code(source_path: Path) -> int:
    version_name = source_version_name(source_path)
    digits = "".join(ch for ch in version_name if ch.isdigit())
    if not digits:
        return 0
    return int(digits[:9])


def patched_unsigned_asset_name(app: ManagedApp, source_path: Path) -> str:
    return f"{app.id}-{source_version_name(source_path)}-patched-unsigned.apk"


def patched_signed_asset_name(app: ManagedApp, source_path: Path) -> str:
    return managed_asset_name(app, source_version_name(source_path))


def normalize_version_name(version: str) -> str:
    return version.strip().replace("_", ".")
