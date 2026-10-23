from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from apk_forge.errors import ForgeError
from apk_forge.github_release import GitHubReleaseClient, ReleaseSpec, github_asset_name
from apk_forge.releases import source_version_name
from apk_forge.source_apk import SOURCE_PACKAGE_EXTENSIONS, sha256_file
from apk_forge.source_icon import extract_source_icon

DEFAULT_SOURCE_RELEASE_TAG = "source-apks"
DEFAULT_SOURCE_RELEASE_TITLE = "Source APKs"
DEFAULT_ICON_RELEASE_TAG = "app-icons"
DEFAULT_ICON_RELEASE_TITLE = "App Icons"
SOURCE_ICON_EXTENSIONS = {".png", ".webp", ".jpg", ".jpeg"}
DEFAULT_ICON_RELEASE_BODY = (
    "### Application Icons\n\n"
    "Icon image assets used by the application catalog. These files are not installable packages.\n"
)


class SourcePublishError(ForgeError):
    """Raised when source package publishing cannot complete."""


@dataclass(frozen=True)
class SourcePublishResult:
    action: str
    app_id: str
    asset: str | None = None
    sha256: str | None = None
    icon: str | None = None


@dataclass(frozen=True)
class SourcePublishSummary:
    results: tuple[SourcePublishResult, ...]
    config_path: Path


def publish_source_packages(
    *,
    config_path: Path,
    vault_root: Path,
    repository: str,
    github_token: str,
    body_template_path: Path,
    release_tag: str = DEFAULT_SOURCE_RELEASE_TAG,
    release_title: str = DEFAULT_SOURCE_RELEASE_TITLE,
    app_id: str | None = None,
    source_package_path: Path | None = None,
    all_apps: bool = False,
    skip_upload: bool = False,
    remove_missing: bool = False,
    force: bool = False,
    client: GitHubReleaseClient | None = None,
) -> SourcePublishSummary:
    if all_apps and source_package_path is not None:
        raise SourcePublishError("--apk-path cannot be used with --all")
    if not all_apps and not app_id:
        raise SourcePublishError("--app-id is required unless --all is used")
    if remove_missing and not all_apps:
        raise SourcePublishError("--remove-missing can only be used with --all")

    config = _load_raw_config(config_path)
    release_spec = _release_spec(repository, release_tag, release_title, body_template_path)
    release_client = None if skip_upload else client if client is not None else GitHubReleaseClient(github_token)
    icon_release_spec = _icon_release_spec(repository, vault_root)

    if all_apps:
        results = _publish_all_sources(
            config=config,
            config_path=config_path,
            vault_root=vault_root,
            release_spec=release_spec,
            release_client=release_client,
            skip_upload=skip_upload,
            remove_missing=remove_missing,
            force=force,
            icon_release_spec=icon_release_spec,
        )
    else:
        results = (
            _publish_one_source(
                config=config,
                config_path=config_path,
                vault_root=vault_root,
                release_spec=release_spec,
                app_id=app_id or "",
                source_package_path=source_package_path,
                release_client=release_client,
                skip_upload=skip_upload,
                force=force,
                icon_release_spec=icon_release_spec,
            ),
        )

    if release_client is not None:
        for asset_name in release_client.release_asset_names(repository, release_tag):
            if Path(asset_name).suffix.lower() in SOURCE_ICON_EXTENSIONS:
                release_client.remove_asset_by_name(release_spec, asset_name)
        if all_apps and remove_missing:
            current_config = _load_raw_config(config_path)
            release_client.prune_assets(
                icon_release_spec,
                _referenced_icon_assets(current_config),
                SOURCE_ICON_EXTENSIONS,
            )

    return SourcePublishSummary(results=tuple(results), config_path=config_path)


def _publish_all_sources(
    *,
    config: dict,
    config_path: Path,
    vault_root: Path,
    release_spec: ReleaseSpec,
    release_client: GitHubReleaseClient | None,
    skip_upload: bool,
    remove_missing: bool,
    force: bool,
    icon_release_spec: ReleaseSpec,
) -> tuple[SourcePublishResult, ...]:
    configured_ids = {
        app.get("id")
        for app in config.get("apps", [])
        if isinstance(app, dict) and isinstance(app.get("id"), str)
    }
    source_root = vault_root / "sources"
    source_ids = {
        path.name
        for path in source_root.iterdir()
        if path.is_dir() and path.name and not path.name.startswith(".")
    } if source_root.is_dir() else set()

    results: list[SourcePublishResult] = []
    for configured_id in sorted(configured_ids):
        if configured_id not in source_ids:
            if remove_missing:
                removed_asset = _remove_app_from_config(config, configured_id)
                _save_raw_config(config_path, config)
                if removed_asset and release_client is not None:
                    release_client.remove_asset_by_name(release_spec, removed_asset)
                results.append(SourcePublishResult(action="removed missing", app_id=configured_id))
            else:
                results.append(SourcePublishResult(action="missing source", app_id=configured_id))
            continue

        results.append(
            _publish_one_source(
                config=config,
                config_path=config_path,
                vault_root=vault_root,
                release_spec=release_spec,
                app_id=configured_id,
                source_package_path=None,
                release_client=release_client,
                skip_upload=skip_upload,
                force=force,
                icon_release_spec=icon_release_spec,
            )
        )
        config = _load_raw_config(config_path)

    for source_id in sorted(source_ids - configured_ids):
        results.append(SourcePublishResult(action="unconfigured source directory", app_id=source_id))

    if remove_missing and release_client is not None:
        config = _load_raw_config(config_path)
        removed_assets = release_client.prune_assets(
            release_spec,
            _referenced_source_assets(config, release_spec.repository, release_spec.tag),
            SOURCE_PACKAGE_EXTENSIONS,
        )
        for asset_name in removed_assets:
            results.append(
                SourcePublishResult(action="removed unreferenced asset", app_id="", asset=asset_name)
            )

    return tuple(results)


def _publish_one_source(
    *,
    config: dict,
    config_path: Path,
    vault_root: Path,
    release_spec: ReleaseSpec,
    app_id: str,
    source_package_path: Path | None,
    release_client: GitHubReleaseClient | None,
    skip_upload: bool,
    force: bool,
    icon_release_spec: ReleaseSpec,
) -> SourcePublishResult:
    app = _find_app(config, app_id, config_path)
    source_package = _resolve_source_package(vault_root, app_id, source_package_path)
    icon_path = extract_source_icon(
        source_package,
        app_id,
        vault_root / "tmp" / "source-icons",
    )
    digest = sha256_file(source_package)
    version_name = source_version_name(source_package)
    icon_digest = sha256_file(icon_path) if icon_path is not None else None
    remote_asset_name = github_asset_name(source_package.name)
    icon_unchanged = _source_icon_config_matches(
        app,
        icon_path.name if icon_path is not None else None,
        icon_digest,
    )
    unchanged = _source_config_matches(app, release_spec, remote_asset_name, digest)
    previous_asset = _configured_source_asset(app, release_spec)
    remote_has_asset = False

    if release_client is not None:
        remote_has_asset = remote_asset_name in release_client.release_asset_names(
            release_spec.repository,
            release_spec.tag,
        )
        if force or not unchanged or not remote_has_asset:
            release_client.publish_asset(
                release_spec,
                source_package,
                SOURCE_PACKAGE_EXTENSIONS,
                asset_name=remote_asset_name,
            )
        if icon_path is not None:
            icon_exists_remotely = icon_path.name in release_client.release_asset_names(
                icon_release_spec.repository,
                icon_release_spec.tag,
            )
            if force or not icon_unchanged or not icon_exists_remotely:
                release_client.publish_asset(
                    icon_release_spec,
                    icon_path,
                    SOURCE_ICON_EXTENSIONS,
                )
            for extension in SOURCE_ICON_EXTENSIONS:
                previous_icon = f"{app_id}-icon{extension}"
                if previous_icon != icon_path.name:
                    release_client.remove_asset_by_name(icon_release_spec, previous_icon)

    _update_source_config(
        config=config,
        config_path=config_path,
        app_id=app_id,
        repository=release_spec.repository,
        release_tag=release_spec.tag,
        asset=remote_asset_name,
        digest=digest,
        version_name=version_name,
        icon_asset=icon_path.name if icon_path is not None else None,
        icon_digest=icon_digest,
    )
    if (
        release_client is not None
        and previous_asset is not None
        and github_asset_name(previous_asset) != remote_asset_name
    ):
        release_client.remove_asset_by_name(release_spec, github_asset_name(previous_asset))

    if skip_upload:
        action = "unchanged" if unchanged else "configured"
    elif unchanged and remote_has_asset and icon_unchanged and not force:
        action = "unchanged"
    elif unchanged and not remote_has_asset:
        action = "uploaded missing remote"
    else:
        action = "updated"
    return SourcePublishResult(
        action=action,
        app_id=app_id,
        asset=remote_asset_name,
        sha256=digest,
        icon=icon_path.name if icon_path is not None else None,
    )


def _resolve_source_package(vault_root: Path, app_id: str, source_package_path: Path | None) -> Path:
    if source_package_path is not None:
        resolved = source_package_path.resolve()
        if not resolved.is_file():
            raise SourcePublishError(f"Source package does not exist: {resolved}")
        if resolved.suffix.lower() not in SOURCE_PACKAGE_EXTENSIONS:
            raise SourcePublishError(
                f"Source package must be one of {sorted(SOURCE_PACKAGE_EXTENSIONS)}: {resolved}"
            )
        return resolved

    source_dir = vault_root / "sources" / app_id
    if not source_dir.is_dir():
        raise SourcePublishError(f"Source directory does not exist: {source_dir}")

    packages = sorted(
        path for path in source_dir.iterdir()
        if path.is_file() and path.suffix.lower() in SOURCE_PACKAGE_EXTENSIONS
    )
    if not packages:
        raise SourcePublishError(f"No source package found in {source_dir}")
    if len(packages) > 1:
        raise SourcePublishError(
            f"Multiple source packages found in {source_dir}. "
            "Keep exactly one source package or pass --apk-path."
        )
    return packages[0].resolve()


def _release_spec(
    repository: str,
    release_tag: str,
    release_title: str,
    body_template_path: Path,
) -> ReleaseSpec:
    return ReleaseSpec(
        repository=repository,
        tag=release_tag,
        title=release_title,
        body_template=body_template_path.read_text(encoding="utf-8"),
    )


def _icon_release_spec(repository: str, vault_root: Path) -> ReleaseSpec:
    template_path = vault_root / "docs" / "app-icons-release.md"
    body_template = (
        template_path.read_text(encoding="utf-8")
        if template_path.is_file()
        else DEFAULT_ICON_RELEASE_BODY
    )
    return ReleaseSpec(
        repository=repository,
        tag=DEFAULT_ICON_RELEASE_TAG,
        title=DEFAULT_ICON_RELEASE_TITLE,
        body_template=body_template,
        asset_extensions=frozenset(SOURCE_ICON_EXTENSIONS),
        empty_asset_message="No application icons published yet.",
    )


def _load_raw_config(config_path: Path) -> dict:
    try:
        config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise SourcePublishError(f"Config file does not exist: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise SourcePublishError(f"Config file is not valid JSON: {exc}") from exc

    if not isinstance(config.get("apps"), list):
        raise SourcePublishError(f"Config file must contain an apps array: {config_path}")
    return config


def _save_raw_config(config_path: Path, config: dict) -> None:
    config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _find_app(config: dict, app_id: str, config_path: Path) -> dict:
    matches = [
        app for app in config.get("apps", [])
        if isinstance(app, dict) and app.get("id") == app_id
    ]
    if not matches:
        raise SourcePublishError(f"App id not found in {config_path}: {app_id}")
    if len(matches) > 1:
        raise SourcePublishError(f"Multiple apps with id found in {config_path}: {app_id}")
    return matches[0]


def _source_config_matches(
    app: dict,
    spec: ReleaseSpec,
    asset: str,
    digest: str,
) -> bool:
    current = app.get("sourceApk", {})
    return (
        isinstance(current, dict)
        and current.get("type") == "githubReleaseAsset"
        and current.get("repository") == spec.repository
        and current.get("release") == spec.tag
        and current.get("asset") == asset
        and current.get("sha256") == digest
    )


def _source_icon_config_matches(app: dict, asset: str | None, digest: str | None) -> bool:
    if asset is None or digest is None:
        return True
    current = app.get("icon", {})
    if not isinstance(current, dict):
        return False
    return (
        current.get("release") == DEFAULT_ICON_RELEASE_TAG
        and current.get("asset") == asset
        and current.get("sha256") == digest
    )


def _configured_source_asset(app: dict, spec: ReleaseSpec) -> str | None:
    current = app.get("sourceApk", {})
    if not isinstance(current, dict):
        return None
    if current.get("type") != "githubReleaseAsset":
        return None
    if current.get("repository") != spec.repository or current.get("release") != spec.tag:
        return None
    asset = current.get("asset")
    return asset if isinstance(asset, str) else None


def _update_source_config(
    *,
    config: dict,
    config_path: Path,
    app_id: str,
    repository: str,
    release_tag: str,
    asset: str,
    digest: str,
    version_name: str,
    icon_asset: str | None,
    icon_digest: str | None,
) -> None:
    app = _find_app(config, app_id, config_path)
    app["sourceApk"] = {
        "type": "githubReleaseAsset",
        "repository": repository,
        "release": release_tag,
        "asset": asset,
        "sha256": digest,
        "versionName": version_name,
    }
    if icon_asset is not None and icon_digest is not None:
        app["icon"] = {
            "release": DEFAULT_ICON_RELEASE_TAG,
            "asset": icon_asset,
            "sha256": icon_digest,
        }
    _save_raw_config(config_path, config)


def _remove_app_from_config(config: dict, app_id: str) -> str | None:
    app = _find_app(config, app_id, Path("apps.json"))
    source = app.get("sourceApk", {})
    removed_asset = source.get("asset") if isinstance(source, dict) and source.get("type") == "githubReleaseAsset" else None
    config["apps"] = [
        candidate for candidate in config.get("apps", [])
        if not isinstance(candidate, dict) or candidate.get("id") != app_id
    ]
    return removed_asset if isinstance(removed_asset, str) else None


def _referenced_source_assets(config: dict, repository: str, release_tag: str) -> set[str]:
    assets: set[str] = set()
    for app in config.get("apps", []):
        if not isinstance(app, dict):
            continue
        source = app.get("sourceApk", {})
        if not isinstance(source, dict):
            continue
        if source.get("type") != "githubReleaseAsset":
            continue
        if source.get("repository") != repository or source.get("release") != release_tag:
            continue
        asset = source.get("asset")
        if isinstance(asset, str):
            assets.add(asset)
    return assets


def _referenced_icon_assets(config: dict) -> set[str]:
    return {
        f"{app['id']}-icon{extension}"
        for app in config.get("apps", [])
        if isinstance(app, dict) and isinstance(app.get("id"), str)
        for extension in SOURCE_ICON_EXTENSIONS
    }


def format_source_publish_summary(summary: SourcePublishSummary) -> str:
    lines = [f"Source sync: {len(summary.results)} result(s)", f"Config: {summary.config_path}"]
    for result in summary.results:
        if result.asset and result.sha256:
            lines.append(f"{result.action}: {result.app_id} -> {result.asset} ({result.sha256})")
            if result.icon:
                lines.append(f"  Icon extracted: {result.icon}")
            else:
                lines.append("  Icon extracted: no")
        elif result.asset:
            lines.append(f"{result.action}: {result.asset}")
        else:
            lines.append(f"{result.action}: {result.app_id}")
    return "\n".join(lines)
