from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from apk_forge.catalog import Catalog, CatalogApp, load_catalog
from apk_forge.config import load_apps_config
from apk_forge.github_release import GitHubReleaseClient, GitHubReleaseError
from apk_forge.models import AppsConfig, ManagedApp, PlannedApp
from apk_forge.mpp import resolve_mpp_identifier
from apk_forge.pipeline import BuildResult, run_local_build
from apk_forge.publish import PublishResult, publish_signed_workspace_outputs
from apk_forge.planner import create_plan
from apk_forge.releases import patched_signed_asset_name, source_version_code, source_version_name


@dataclass(frozen=True)
class SyncResult:
    build: BuildResult
    publish: PublishResult
    skipped: tuple[str, ...] = ()


def sync_build_and_publish(
    config: AppsConfig,
    vault_root: Path,
    workspace_root: Path,
    catalog_path: Path,
    repository: str,
    github_token: str,
    body_template_path: Path,
    release_tag: str = "patched-apks",
    release_title: str = "Patched APKs",
    morphe_cli_jar: Path | None = None,
    apkeditor_jar: Path | None = None,
    apksigner: Path | None = None,
    keystore: Path | None = None,
    key_alias: str | None = "public",
    keystore_password: str | None = "public",
    key_password: str | None = "public",
    force: bool = False,
) -> SyncResult:
    release_list_config = config
    skipped: tuple[str, ...] = ()
    if not force:
        config, skipped = filter_unchanged_apps(
            config=config,
            vault_root=vault_root,
            workspace_root=workspace_root,
            catalog_path=catalog_path,
            repository=repository,
            github_token=github_token,
            release_tag=release_tag,
        )

    build_result = run_local_build(
        config=config,
        vault_root=vault_root,
        workspace_root=workspace_root,
        morphe_cli_jar=morphe_cli_jar,
        github_token=github_token,
        apkeditor_jar=apkeditor_jar,
        apksigner=apksigner,
        keystore=keystore,
        key_alias=key_alias,
        keystore_password=keystore_password,
        key_password=key_password,
    )
    publish_result = publish_signed_workspace_outputs(
        config=config,
        vault_root=vault_root,
        workspace_root=workspace_root,
        catalog_path=catalog_path,
        repository=repository,
        github_token=github_token,
        body_template_path=body_template_path,
        release_tag=release_tag,
        release_title=release_title,
        release_list_config=release_list_config,
        mpp_paths={app.id: app.patches_path for app in build_result.apps},
    )
    return SyncResult(build=build_result, publish=publish_result, skipped=skipped)


def sync_from_paths(
    config_path: Path,
    vault_root: Path,
    workspace_root: Path,
    catalog_path: Path,
    repository: str,
    github_token: str,
    body_template_path: Path,
    release_tag: str = "patched-apks",
    release_title: str = "Patched APKs",
    morphe_cli_jar: Path | None = None,
    apkeditor_jar: Path | None = None,
    apksigner: Path | None = None,
    keystore: Path | None = None,
    key_alias: str | None = "public",
    keystore_password: str | None = "public",
    key_password: str | None = "public",
    force: bool = False,
) -> SyncResult:
    return sync_build_and_publish(
        config=load_apps_config(config_path),
        vault_root=vault_root,
        workspace_root=workspace_root,
        catalog_path=catalog_path,
        repository=repository,
        github_token=github_token,
        body_template_path=body_template_path,
        release_tag=release_tag,
        release_title=release_title,
        morphe_cli_jar=morphe_cli_jar,
        apkeditor_jar=apkeditor_jar,
        apksigner=apksigner,
        keystore=keystore,
        key_alias=key_alias,
        keystore_password=keystore_password,
        key_password=key_password,
        force=force,
    )


def filter_unchanged_apps(
    config: AppsConfig,
    vault_root: Path,
    workspace_root: Path,
    catalog_path: Path,
    repository: str,
    github_token: str,
    release_tag: str,
) -> tuple[AppsConfig, tuple[str, ...]]:
    catalog = load_catalog(catalog_path) if catalog_path.is_file() else Catalog.empty()
    catalog_by_id = {
        app.id: app for app in catalog.apps
        if app.type == "managed"
    }
    release_assets = _release_asset_names(repository, release_tag, github_token)
    changed_apps: list[ManagedApp] = []
    skipped: list[str] = []

    for planned in create_plan(config, vault_root, github_token, workspace_root):
        mpp_identifier = resolve_mpp_identifier(planned.app.mpp, github_token)
        if is_planned_app_unchanged(
            planned,
            catalog_by_id.get(planned.app.id),
            release_assets,
            release_tag,
            mpp_identifier,
        ):
            skipped.append(planned.app.id)
        else:
            changed_apps.append(planned.app)

    return config.with_apps(tuple(changed_apps)), tuple(skipped)


def is_planned_app_unchanged(
    planned: PlannedApp,
    catalog_app: CatalogApp | None,
    release_assets: set[str],
    release_tag: str,
    mpp_identifier: str | None = None,
) -> bool:
    if catalog_app is None:
        return False
    expected_asset = patched_signed_asset_name(planned.app, planned.source_path)
    return (
        catalog_app.version_name == source_version_name(planned.source_path)
        and catalog_app.version_code == source_version_code(planned.source_path)
        and catalog_app.release == release_tag
        and catalog_app.asset == expected_asset
        and (mpp_identifier is None or catalog_app.mpp == mpp_identifier)
        and expected_asset in release_assets
    )


def _release_asset_names(repository: str, release_tag: str, github_token: str) -> set[str]:
    try:
        return GitHubReleaseClient(github_token).release_asset_names(repository, release_tag)
    except GitHubReleaseError as exc:
        if "HTTP 404" in str(exc):
            return set()
        raise


def format_sync_result(result: SyncResult) -> str:
    lines = [
        f"Build completed: {len(result.build.apps)} app(s)",
        f"Published: {len(result.publish.apps)} app(s)",
        f"Skipped unchanged: {len(result.skipped)} app(s)",
        f"Catalog: {result.publish.catalog_path}",
    ]
    if result.skipped:
        lines.append(f"Skipped IDs: {', '.join(result.skipped)}")
    return "\n\n".join(lines)
