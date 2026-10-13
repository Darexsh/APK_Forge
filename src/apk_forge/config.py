from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from apk_forge.errors import ConfigError
from apk_forge.models import AppsConfig, ManagedApp, MppSource, OutputConfig, PatchSelection, SourceApk

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_SHA256_PATTERN = re.compile(r"^[a-fA-F0-9]{64}$")


def load_apps_config(path: Path) -> AppsConfig:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Config file does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Config file is not valid JSON: {exc}") from exc

    data = _with_external_mpp_sources(path, data)
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

    mpp_sources = _parse_mpp_sources(data.get("mppSources"))
    apps = tuple(_parse_app(index, raw_app, mpp_sources) for index, raw_app in enumerate(apps_data))
    _validate_unique_ids(apps)
    _validate_unique_packages(apps)
    return AppsConfig(schema_version=schema_version, apps=apps)


def _with_external_mpp_sources(path: Path, data: dict[str, Any]) -> dict[str, Any]:
    mpp_sources_dir = path.parent / "mpp_sources"
    if not mpp_sources_dir.is_dir():
        return data

    external_sources: dict[str, Any] = {}
    for source_file in sorted(mpp_sources_dir.glob("*.json")):
        try:
            raw_sources = json.loads(source_file.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{source_file} is not valid JSON: {exc}") from exc
        if not isinstance(raw_sources, dict):
            raise ConfigError(f"{source_file} root must be an object")
        for key, value in raw_sources.items():
            if key in external_sources:
                raise ConfigError(f"Duplicate MPP source key in mpp_sources: {key}")
            external_sources[key] = value

    if not external_sources:
        return data

    merged = dict(data)
    inline_sources = merged.get("mppSources", {})
    if inline_sources is None:
        inline_sources = {}
    if not isinstance(inline_sources, dict):
        raise ConfigError("mppSources must be an object")
    duplicate_keys = set(external_sources).intersection(inline_sources)
    if duplicate_keys:
        duplicate = sorted(duplicate_keys)[0]
        raise ConfigError(f"Duplicate MPP source key: {duplicate}")
    merged["mppSources"] = {**external_sources, **inline_sources}
    return merged


def _parse_mpp_sources(data: Any) -> dict[str, MppSource]:
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError("mppSources must be an object")

    sources: dict[str, MppSource] = {}
    for key, value in data.items():
        where = f"mppSources.{key}"
        if not isinstance(key, str) or not _ID_PATTERN.match(key):
            raise ConfigError("mppSources keys must use lowercase letters, numbers, and hyphens")
        sources[key] = _parse_mpp_object(value, where)
    return sources


def _parse_app(index: int, data: Any, mpp_sources: dict[str, MppSource]) -> ManagedApp:
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

    mpp = _parse_mpp(data.get("mpp"), where, mpp_sources)
    source_apk = _parse_source_apk(data.get("sourceApk"), where)
    output = _parse_output(data.get("output"), app_id, where)
    patches = _parse_patch_selection(data.get("patches"), where)

    return ManagedApp(
        id=app_id,
        name=name,
        package_name=package_name,
        enabled=enabled,
        mpp=mpp,
        source_apk=source_apk,
        output=output,
        patches=patches,
    )


def _parse_mpp(data: Any, parent: str, mpp_sources: dict[str, MppSource]) -> MppSource:
    where = f"{parent}.mpp"
    if isinstance(data, str):
        key = data.strip()
        if not key:
            raise ConfigError(f"{where} must be a non-empty source key")
        try:
            return mpp_sources[key]
        except KeyError as exc:
            raise ConfigError(f"{where} references unknown MPP source: {key}") from exc
    return _parse_mpp_object(data, where)


def _parse_mpp_object(data: Any, where: str) -> MppSource:
    if not isinstance(data, dict):
        raise ConfigError(f"{where} must be an object or source key")
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


def _parse_patch_selection(data: Any, parent: str) -> PatchSelection:
    if data is None:
        return PatchSelection()

    where = f"{parent}.patches"
    if not isinstance(data, dict):
        raise ConfigError(f"{where} must be an object")

    return PatchSelection(
        enable=_optional_string_array(data, "enable", where),
        disable=_optional_string_array(data, "disable", where),
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


def _optional_string_array(data: dict[str, Any], key: str, where: str) -> tuple[str, ...]:
    value = data.get(key, [])
    if not isinstance(value, list):
        raise ConfigError(f"{where}.{key} must be an array")
    parsed: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ConfigError(f"{where}.{key}[{index}] must be a non-empty string")
        parsed.append(item)
    return tuple(parsed)


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
