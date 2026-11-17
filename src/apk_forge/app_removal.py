from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from apk_forge.catalog import load_catalog
from apk_forge.config import load_apps_config
from apk_forge.errors import ForgeError
from apk_forge.github_release import GitHubReleaseClient, GitHubReleaseError, ReleaseSpec, github_asset_name

ICON_EXTENSIONS = frozenset({".png", ".webp", ".jpg", ".jpeg"})


class AppRemovalError(ForgeError):
    """Raised when a managed app cannot be safely removed."""


@dataclass(frozen=True)
class RemovalAsset:
    release: str
    name: str
    kind: str
    exists: bool


@dataclass(frozen=True)
class AppRemovalPlan:
    app_id: str
    app_name: str
    config_path: Path
    catalog_path: Path
    config: dict[str, Any]
    catalog: dict[str, Any]
    remaining_config: dict[str, Any]
    remaining_catalog: dict[str, Any]
    assets: tuple[RemovalAsset, ...]
    source_directory: Path
    source_directory_exists: bool


def plan_app_removal(
    *,
    app_id: str,
    config_path: Path,
    catalog_path: Path,
    vault_root: Path,
    repository: str,
    client: GitHubReleaseClient,
) -> AppRemovalPlan:
    # Validate the complete inputs before planning any remote deletions.
    load_apps_config(config_path)
    load_catalog(catalog_path)
    config = _read_object(config_path, "app config")
    catalog = _read_object(catalog_path, "catalog")
    apps = config.get("apps")
    catalog_apps = catalog.get("apps")
    if not isinstance(apps, list):
        raise AppRemovalError(f"App config must contain an apps array: {config_path}")
    if not isinstance(catalog_apps, list):
        raise AppRemovalError(f"Catalog must contain an apps array: {catalog_path}")

    matching_apps = [
        app for app in apps
        if isinstance(app, dict) and app.get("id") == app_id
    ]
    if not matching_apps:
        raise AppRemovalError(f"Managed app id not found in config: {app_id}")
    if len(matching_apps) > 1:
        raise AppRemovalError(f"App config contains duplicate app id: {app_id}")

    app = matching_apps[0]
    source_apk = app.get("sourceApk")
    if not isinstance(source_apk, dict):
        raise AppRemovalError(f"App has no valid sourceApk configuration: {app_id}")
    if source_apk.get("type") == "githubReleaseAsset":
        source_repository = source_apk.get("repository")
        if source_repository != repository:
            raise AppRemovalError(
                f"Source APK for {app_id} is in {source_repository!r}; "
                f"this command only removes assets from {repository!r}."
            )

    matching_catalog_apps = [
        item for item in catalog_apps
        if isinstance(item, dict) and item.get("id") == app_id and item.get("type") == "managed"
    ]
    remaining_config = {
        **config,
        "apps": [
            item for item in apps
            if not (isinstance(item, dict) and item.get("id") == app_id)
        ],
    }
    remaining_catalog = {
        **catalog,
        "apps": [
            item for item in catalog_apps
            if not (isinstance(item, dict) and item.get("id") == app_id and item.get("type") == "managed")
        ],
    }
    if matching_catalog_apps:
        remaining_catalog["generatedAt"] = datetime.now(UTC).replace(microsecond=0).isoformat()

    candidates: list[tuple[str, str, str]] = []
    if source_apk.get("type") == "githubReleaseAsset":
        asset = source_apk.get("asset")
        release = source_apk.get("release")
        if isinstance(asset, str) and asset and isinstance(release, str) and release:
            candidates.append((release, github_asset_name(asset), "source APK"))

    for item in matching_catalog_apps:
        release = item.get("release")
        asset = item.get("asset")
        if isinstance(release, str) and release and isinstance(asset, str) and asset:
            candidates.append((release, github_asset_name(asset), "patched APK"))

    orphaned_icons = _orphaned_icon_refs(
        app,
        matching_catalog_apps,
        remaining_config,
        remaining_catalog,
        vault_root / "archive.json",
    )
    for release, asset in orphaned_icons:
        candidates.append((release, asset, "unreferenced icon"))

    assets: list[RemovalAsset] = []
    seen: set[tuple[str, str]] = set()
    for release, asset, kind in candidates:
        key = (release, asset)
        if key in seen:
            continue
        seen.add(key)
        exists = asset in client.release_asset_names(repository, release)
        assets.append(RemovalAsset(release=release, name=asset, kind=kind, exists=exists))

    return AppRemovalPlan(
        app_id=app_id,
        app_name=str(app.get("name") or app_id),
        config_path=config_path,
        catalog_path=catalog_path,
        config=config,
        catalog=catalog,
        remaining_config=remaining_config,
        remaining_catalog=remaining_catalog,
        assets=tuple(assets),
        source_directory=vault_root / "sources" / app_id,
        source_directory_exists=(vault_root / "sources" / app_id).is_dir(),
    )


def format_app_removal_plan(plan: AppRemovalPlan) -> str:
    lines = [f"App removal preview: {plan.app_name} ({plan.app_id})", "", "Local changes:"]
    lines.append(f"- Remove app entry from {plan.config_path}")
    if any(
        isinstance(item, dict) and item.get("id") == plan.app_id and item.get("type") == "managed"
        for item in plan.catalog.get("apps", [])
    ):
        lines.append(f"- Remove managed catalog entry from {plan.catalog_path}")
    else:
        lines.append(f"- No managed catalog entry found in {plan.catalog_path}")
    if plan.source_directory_exists:
        lines.append(f"- Keep local source files in {plan.source_directory}")

    lines.extend(["", "GitHub release assets:"])
    if not plan.assets:
        lines.append("- No related release assets identified")
    for asset in plan.assets:
        action = "delete" if asset.exists else "already absent"
        lines.append(f"- {action}: {asset.release}/{asset.name} ({asset.kind})")
    lines.extend(["", "Preview only. Add --apply to perform these changes."])
    return "\n".join(lines)


def apply_app_removal(
    plan: AppRemovalPlan,
    *,
    repository: str,
    vault_root: Path,
    client: GitHubReleaseClient,
) -> None:
    source_template = _read_template(vault_root / "docs" / "source-apks-release.md")
    patched_template = _read_template(vault_root / "docs" / "patched-apks-release.md")
    icon_template_path = vault_root / "docs" / "app-icons-release.md"
    icon_template = (
        icon_template_path.read_text(encoding="utf-8")
        if icon_template_path.is_file()
        else "### Application Icons\n\nIcon image assets used by the application catalog.\n"
    )

    patched_release_assets: dict[str, list[dict[str, Any]]] = {}
    for item in plan.remaining_catalog.get("apps", []):
        if not isinstance(item, dict) or item.get("type") != "managed":
            continue
        release = item.get("release")
        if isinstance(release, str):
            patched_release_assets.setdefault(release, []).append(item)

    for asset in plan.assets:
        if not asset.exists:
            continue
        template = source_template if asset.kind == "source APK" else icon_template
        if asset.kind == "patched APK":
            template = patched_template
        spec = ReleaseSpec(
            repository=repository,
            tag=asset.release,
            title=_release_title(asset.kind, asset.release),
            body_template=template,
        )
        if asset.kind == "unreferenced icon":
            spec = ReleaseSpec(
                repository=repository,
                tag=asset.release,
                title=_release_title(asset.kind, asset.release),
                body_template=icon_template,
                asset_extensions=ICON_EXTENSIONS,
                empty_asset_message="No application icons published yet.",
            )
        if asset.kind == "patched APK":
            spec = ReleaseSpec(
                repository=repository,
                tag=asset.release,
                title="Patched APKs",
                body_template=patched_template,
                asset_list=_format_patched_asset_list(patched_release_assets.get(asset.release, [])),
                asset_extensions=frozenset({".apk"}),
                empty_asset_message="No APK assets listed yet.",
            )
        client.remove_asset_by_name(spec, asset.name)

    # If the catalog row existed but its release asset was already absent, the
    # patched release description still needs to reflect the local catalog edit.
    patched_tags = {
        item.get("release", "patched-apks")
        for item in plan.catalog.get("apps", [])
        if isinstance(item, dict) and item.get("id") == plan.app_id and item.get("type") == "managed"
    }
    for release in patched_tags:
        if not isinstance(release, str):
            continue
        spec = ReleaseSpec(
            repository=repository,
            tag=release,
            title="Patched APKs",
            body_template=patched_template,
            asset_list=_format_patched_asset_list(patched_release_assets.get(release, [])),
            asset_extensions=frozenset({".apk"}),
            empty_asset_message="No APK assets listed yet.",
        )
        try:
            remote_release = client.get_release(repository, release)
        except GitHubReleaseError as exc:
            if "HTTP 404" in str(exc):
                continue
            raise
        client.update_release_metadata(spec, remote_release)

    _write_json(plan.config_path, plan.remaining_config)
    _write_json(plan.catalog_path, plan.remaining_catalog)


def _release_title(kind: str, release: str) -> str:
    if kind == "source APK":
        return "Source APKs"
    if release == "app-icons":
        return "App Icons"
    return release


def _orphaned_icon_refs(
    app: dict[str, Any],
    matching_catalog_apps: list[dict[str, Any]],
    remaining_config: dict[str, Any],
    remaining_catalog: dict[str, Any],
    archive_path: Path,
) -> tuple[tuple[str, str], ...]:
    target_refs = _icon_refs([app, *matching_catalog_apps])
    if not target_refs:
        return ()
    remaining_objects: list[dict[str, Any]] = []
    for source in (remaining_config, remaining_catalog):
        items = source.get("apps", [])
        if isinstance(items, list):
            remaining_objects.extend(item for item in items if isinstance(item, dict))
    if archive_path.is_file():
        archive = _read_object(archive_path, "archive catalog")
        archive_apps = archive.get("apps", [])
        if isinstance(archive_apps, list):
            remaining_objects.extend(item for item in archive_apps if isinstance(item, dict))
    remaining_refs = _icon_refs(remaining_objects)
    return tuple(sorted(target_refs - remaining_refs))


def _icon_refs(items: list[dict[str, Any]]) -> set[tuple[str, str]]:
    refs: set[tuple[str, str]] = set()
    for item in items:
        icon = item.get("icon")
        if not isinstance(icon, dict):
            continue
        release = icon.get("release", "app-icons")
        asset = icon.get("asset")
        if isinstance(release, str) and isinstance(asset, str) and release and asset:
            refs.add((release, github_asset_name(asset)))
    return refs


def _format_patched_asset_list(apps: list[dict[str, Any]]) -> str:
    rows = sorted(apps, key=lambda item: (str(item.get("name", "")).lower(), str(item.get("id", ""))))
    if not rows:
        return "- _No APK assets listed yet._"
    lines: list[str] = []
    for app in rows:
        asset = app.get("asset")
        if not isinstance(asset, str):
            continue
        lines.append(f"- `{asset}`")
        lines.append(f"  - App: {app.get('name', app.get('id', ''))} (`{app.get('packageName', '')}`)")
        lines.append(f"  - Version: {app.get('versionName', '')} ({app.get('versionCode', '')})")
        if app.get("mpp"):
            lines.append(f"  - MPP: `{app['mpp']}`")
    return "\n".join(lines) if lines else "- _No APK assets listed yet._"


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise AppRemovalError(f"{label.capitalize()} file does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise AppRemovalError(f"{label.capitalize()} file is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise AppRemovalError(f"{label.capitalize()} root must be a JSON object: {path}")
    return data


def _read_template(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AppRemovalError(f"Release body template could not be read: {path}") from exc


def _write_json(path: Path, data: dict[str, Any]) -> None:
    temp_path = path.with_name(f".{path.name}.apk-forge.tmp")
    temp_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp_path.replace(path)


def format_apply_result(plan: AppRemovalPlan) -> str:
    removed = [asset for asset in plan.assets if asset.exists]
    lines = [f"Removed managed app: {plan.app_name} ({plan.app_id})"]
    lines.append(f"Updated: {plan.config_path}")
    lines.append(f"Updated: {plan.catalog_path}")
    if removed:
        lines.append("Deleted release assets:")
        lines.extend(f"- {asset.release}/{asset.name}" for asset in removed)
    else:
        lines.append("No related release assets were present.")
    lines.append("Commit and push the updated Vault files so downstream catalog consumers receive the change.")
    return "\n".join(lines)
