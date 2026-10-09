from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MppSource:
    owner: str
    repository: str
    path: str | None = None
    ref: str = "main"
    release: str = "latest"
    asset: str | None = None


@dataclass(frozen=True)
class SourceApk:
    type: str
    path: str | None = None
    repository: str | None = None
    release: str | None = None
    asset: str | None = None
    sha256: str | None = None

    def resolve(self, vault_root: Path) -> Path:
        if self.type != "vault":
            raise ValueError(f"Unsupported source APK type: {self.type}")
        if self.path is None:
            raise ValueError("Vault source APK requires path")
        return (vault_root / self.path).resolve()


@dataclass(frozen=True)
class OutputConfig:
    release_prefix: str | None = None
    asset_name: str | None = None


@dataclass(frozen=True)
class ManagedApp:
    id: str
    name: str
    package_name: str
    enabled: bool
    mpp: MppSource
    source_apk: SourceApk
    output: OutputConfig


@dataclass(frozen=True)
class AppsConfig:
    schema_version: int
    apps: tuple[ManagedApp, ...]

    @property
    def enabled_apps(self) -> tuple[ManagedApp, ...]:
        return tuple(app for app in self.apps if app.enabled)

    def with_apps(self, apps: tuple[ManagedApp, ...]) -> AppsConfig:
        return AppsConfig(schema_version=self.schema_version, apps=apps)


@dataclass(frozen=True)
class PlannedApp:
    app: ManagedApp
    source_path: Path
    source_sha256: str
