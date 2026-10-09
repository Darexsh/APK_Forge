from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from apk_forge.catalog import Catalog, CatalogApp, load_catalog, upsert_catalog_app, write_catalog
from apk_forge.config import load_apps_config
from apk_forge.errors import ForgeError
from apk_forge.github_release import GitHubReleaseClient, ReleaseSpec
from apk_forge.models import AppsConfig
from apk_forge.planner import create_plan
from apk_forge.releases import (
    patched_signed_asset_name,
    source_version_code,
    source_version_name,
)
from apk_forge.source_apk import sha256_file

DEFAULT_PATCHED_RELEASE_TAG = "patched-apks"
DEFAULT_PATCHED_RELEASE_TITLE = "Patched APKs"


class PublishError(ForgeError):
    """Raised when patched APK publishing cannot complete."""


@dataclass(frozen=True)
class PublishedApp:
    id: str
    name: str
    package_name: str
    version_name: str
    version_code: int
    release: str
    asset: str
    apk_path: Path
    sha256: str


@dataclass(frozen=True)
class PublishResult:
    apps: tuple[PublishedApp, ...]
    catalog_path: Path


def publish_signed_workspace_outputs(
    config: AppsConfig,
    vault_root: Path,
    workspace_root: Path,
    catalog_path: Path,
    repository: str,
    github_token: str,
    body_template_path: Path,
    release_tag: str = DEFAULT_PATCHED_RELEASE_TAG,
    release_title: str = DEFAULT_PATCHED_RELEASE_TITLE,
    client: GitHubReleaseClient | None = None,
) -> PublishResult:
    body_template = body_template_path.read_text(encoding="utf-8")
    release_client = client or GitHubReleaseClient(github_token)
    release_spec = ReleaseSpec(
        repository=repository,
        tag=release_tag,
        title=release_title,
        body_template=body_template,
    )
    catalog = load_catalog(catalog_path) if catalog_path.is_file() else Catalog.empty()
    published = []

    for planned in create_plan(config, vault_root, github_token, workspace_root):
        apk_path = workspace_root / "build" / planned.app.id / "signed" / patched_signed_asset_name(
            planned.app,
            planned.source_path,
        )
        if not apk_path.is_file():
            raise PublishError(
                f"Signed APK does not exist for {planned.app.id}: {apk_path}\n"
                "Run the build without --skip-signing before publishing."
            )

        release_client.publish_asset(release_spec, apk_path)
        version_name = source_version_name(planned.source_path)
        version_code = source_version_code(planned.source_path)
        digest = sha256_file(apk_path)
        catalog_app = CatalogApp(
            id=planned.app.id,
            name=planned.app.name,
            package_name=planned.app.package_name,
            version_name=version_name,
            version_code=version_code,
            type="managed",
            release=release_tag,
            asset=apk_path.name,
            sha256=digest,
        )
        catalog = upsert_catalog_app(catalog, catalog_app)
        published.append(
            PublishedApp(
                id=planned.app.id,
                name=planned.app.name,
                package_name=planned.app.package_name,
                version_name=version_name,
                version_code=version_code,
                release=release_tag,
                asset=apk_path.name,
                apk_path=apk_path,
                sha256=digest,
            )
        )

    write_catalog(catalog, catalog_path)
    return PublishResult(apps=tuple(published), catalog_path=catalog_path)


def publish_from_paths(
    config_path: Path,
    vault_root: Path,
    workspace_root: Path,
    catalog_path: Path,
    repository: str,
    github_token: str,
    body_template_path: Path,
    release_tag: str = DEFAULT_PATCHED_RELEASE_TAG,
    release_title: str = DEFAULT_PATCHED_RELEASE_TITLE,
) -> PublishResult:
    return publish_signed_workspace_outputs(
        config=load_apps_config(config_path),
        vault_root=vault_root,
        workspace_root=workspace_root,
        catalog_path=catalog_path,
        repository=repository,
        github_token=github_token,
        body_template_path=body_template_path,
        release_tag=release_tag,
        release_title=release_title,
    )


def format_publish_result(result: PublishResult) -> str:
    lines = [f"Published: {len(result.apps)} app(s)", f"Catalog: {result.catalog_path}"]
    for index, app in enumerate(result.apps, start=1):
        lines.extend(
            [
                "",
                f"{index}. {app.name} ({app.id})",
                f"   Package: {app.package_name}",
                f"   Version: {app.version_name} ({app.version_code})",
                f"   Release: {app.release}",
                f"   Asset: {app.asset}",
                f"   APK: {app.apk_path}",
                f"   SHA-256: {app.sha256}",
            ]
        )
    return "\n".join(lines)
