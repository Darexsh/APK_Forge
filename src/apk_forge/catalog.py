from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from apk_forge.errors import ConfigError


@dataclass(frozen=True)
class CatalogApp:
    id: str
    name: str
    package_name: str
    version_name: str
    version_code: int
    type: str
    release: str
    asset: str
    sha256: str

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "packageName": self.package_name,
            "versionName": self.version_name,
            "versionCode": self.version_code,
            "type": self.type,
            "release": self.release,
            "asset": self.asset,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class Catalog:
    schema_version: int
    generated_at: str
    apps: tuple[CatalogApp, ...]

    @classmethod
    def empty(cls) -> Catalog:
        return cls(
            schema_version=1,
            generated_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
            apps=(),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "generatedAt": self.generated_at,
            "apps": [app.to_json() for app in self.apps],
        }


def write_catalog(catalog: Catalog, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(catalog.to_json(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def upsert_catalog_app(catalog: Catalog, catalog_app: CatalogApp) -> Catalog:
    apps = [
        app for app in catalog.apps
        if not (app.type == catalog_app.type and app.id == catalog_app.id)
    ]
    apps.append(catalog_app)
    apps.sort(key=lambda app: (app.type, app.name.lower(), app.id))
    return Catalog(
        schema_version=catalog.schema_version,
        generated_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
        apps=tuple(apps),
    )


def load_catalog(path: Path) -> Catalog:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Catalog file does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Catalog file is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError("Catalog root must be an object")
    if data.get("schemaVersion") != 1:
        raise ConfigError("Catalog schemaVersion must be 1")
    generated_at = data.get("generatedAt")
    if not isinstance(generated_at, str) or not generated_at:
        raise ConfigError("Catalog generatedAt must be a non-empty string")
    apps_data = data.get("apps")
    if not isinstance(apps_data, list):
        raise ConfigError("Catalog apps must be an array")

    apps = tuple(_parse_catalog_app(index, app) for index, app in enumerate(apps_data))
    return Catalog(schema_version=1, generated_at=generated_at, apps=apps)


def _parse_catalog_app(index: int, data: Any) -> CatalogApp:
    where = f"catalog.apps[{index}]"
    if not isinstance(data, dict):
        raise ConfigError(f"{where} must be an object")
    app_type = _required_string(data, "type", where)
    if app_type not in {"managed", "archive"}:
        raise ConfigError(f"{where}.type must be managed or archive")

    version_code = data.get("versionCode")
    if not isinstance(version_code, int):
        raise ConfigError(f"{where}.versionCode must be an integer")

    return CatalogApp(
        id=_required_string(data, "id", where),
        name=_required_string(data, "name", where),
        package_name=_required_string(data, "packageName", where),
        version_name=_required_string(data, "versionName", where),
        version_code=version_code,
        type=app_type,
        release=_required_string(data, "release", where),
        asset=_required_string(data, "asset", where),
        sha256=_required_string(data, "sha256", where),
    )


def _required_string(data: dict[str, Any], key: str, where: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{where}.{key} must be a non-empty string")
    return value
