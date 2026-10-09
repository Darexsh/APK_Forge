from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from apk_forge.errors import ConfigError
from apk_forge.models import AppsConfig, ManagedApp, MppSource, OutputConfig, SourceApk

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_SHA256_PATTERN = re.compile(r"^[a-fA-F0-9]{64}$")


def load_apps_config(path: Path) -> AppsConfig:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Config file does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Config file is not valid JSON: {exc}") from exc

    return parse_apps_config(data)


def parse_apps_config(data: dict[str, Any]) -> AppsConfig:
    if not isinstance(data, dict):
        raise ConfigError("Config root must be an object")

    schema_version = data.get("schemaVersion")
    if schema_version != 1:
        raise ConfigError("schemaVersion must be 1")

    apps_data = data.get("apps")
    if not isinstance(apps_data, list):
        raise ConfigError("apps must be an array")

    apps = tuple(_parse_app(index, raw_app) for index, raw_app in enumerate(apps_data))
    _validate_unique_ids(apps)
    _validate_unique_packages(apps)
    return AppsConfig(schema_version=schema_version, apps=apps)


def _parse_app(index: int, data: Any) -> ManagedApp:
    where = f"apps[{index}]"
    if not isinstance(data, dict):
        raise ConfigError(f"{where} must be an object")

    app_id = _required_string(data, "id", where)
    if not _ID_PATTERN.match(app_id):
        raise ConfigError(f"{where}.id must use lowercase letters, numbers, and hyphens")

    name = _required_string(data, "name", where)
    package_name = _required_string(data, "packageName", where)
    enabled = data.get("enabled")
    if not isinstance(enabled, bool):
        raise ConfigError(f"{where}.enabled must be a boolean")

    mpp = _parse_mpp(data.get("mpp"), where)
    source_apk = _parse_source_apk(data.get("sourceApk"), where)
    output = _parse_output(data.get("output"), app_id, where)

    return ManagedApp(
        id=app_id,
        name=name,
        package_name=package_name,
        enabled=enabled,
        mpp=mpp,
        source_apk=source_apk,
        output=output,
    )


def _parse_mpp(data: Any, parent: str) -> MppSource:
    where = f"{parent}.mpp"
    if not isinstance(data, dict):
        raise ConfigError(f"{where} must be an object")
    return MppSource(
        owner=_required_string(data, "owner", where),
        repository=_required_string(data, "repository", where),
        path=_optional_string(data, "path", None, where),
        ref=_optional_string(data, "ref", "main", where),
        release=_optional_string(data, "release", "latest", where),
        asset=_optional_string(data, "asset", None, where),
    )


def _parse_source_apk(data: Any, parent: str) -> SourceApk:
    where = f"{parent}.sourceApk"
    if not isinstance(data, dict):
        raise ConfigError(f"{where} must be an object")

    source_type = _required_string(data, "type", where)
    sha256 = data.get("sha256")
    if sha256 is not None:
        if not isinstance(sha256, str) or not _SHA256_PATTERN.match(sha256):
            raise ConfigError(f"{where}.sha256 must be a 64-character hex digest")
        sha256 = sha256.lower()

    if source_type == "vault":
        return SourceApk(
            type=source_type,
            path=_required_string(data, "path", where),
            sha256=sha256,
        )

    if source_type == "githubReleaseAsset":
        return SourceApk(
            type=source_type,
            repository=_required_string(data, "repository", where),
            release=_required_string(data, "release", where),
            asset=_required_string(data, "asset", where),
            sha256=sha256,
        )

    raise ConfigError(f"{where}.type must be 'vault' or 'githubReleaseAsset'")


def _parse_output(data: Any, app_id: str, parent: str) -> OutputConfig:
    if data is None:
        return OutputConfig(release_prefix=f"managed-{app_id}", asset_name=None)

    where = f"{parent}.output"
    if not isinstance(data, dict):
        raise ConfigError(f"{where} must be an object")

    release_prefix = _optional_string(data, "releasePrefix", f"managed-{app_id}", where)
    if not _ID_PATTERN.match(release_prefix):
        raise ConfigError(f"{where}.releasePrefix must use lowercase letters, numbers, and hyphens")

    return OutputConfig(
        release_prefix=release_prefix,
        asset_name=_optional_string(data, "assetName", None, where),
    )


def _required_string(data: dict[str, Any], key: str, where: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{where}.{key} must be a non-empty string")
    return value


def _optional_string(data: dict[str, Any], key: str, default: str | None, where: str) -> str | None:
    value = data.get(key, default)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{where}.{key} must be a non-empty string")
    return value


def _validate_unique_ids(apps: tuple[ManagedApp, ...]) -> None:
    seen: set[str] = set()
    for app in apps:
        if app.id in seen:
            raise ConfigError(f"Duplicate app id: {app.id}")
        seen.add(app.id)


def _validate_unique_packages(apps: tuple[ManagedApp, ...]) -> None:
    seen: set[str] = set()
    for app in apps:
        if app.package_name in seen:
            raise ConfigError(f"Duplicate packageName: {app.package_name}")
        seen.add(app.package_name)
