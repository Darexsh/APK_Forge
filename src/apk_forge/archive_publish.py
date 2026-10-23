from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from apk_forge.errors import ForgeError
from apk_forge.github_release import GitHubReleaseClient, ReleaseSpec
from apk_forge.source_apk import sha256_file
from apk_forge.source_icon import IMAGE_SUFFIXES, extract_source_icon

DEFAULT_ARCHIVE_RELEASE_TAG = "archive-apks"
DEFAULT_ARCHIVE_RELEASE_TITLE = "Archive APKs"
ARCHIVE_APK_EXTENSIONS = {".apk"}
ICON_RELEASE_TAG = "app-icons"
ICON_RELEASE_TITLE = "App Icons"
ICON_EXTENSIONS = IMAGE_SUFFIXES
DEFAULT_ICON_RELEASE_BODY = (
    "### Application Icons\n\n"
    "Icon image assets used by the APK catalog and archive. These files are not installable packages.\n"
)


class ArchivePublishError(ForgeError):
    """Raised when archive APK publishing cannot complete."""


@dataclass(frozen=True)
class ArchivePublishResult:
    action: str
    archive_id: str
    asset: str | None = None
    icon: str | None = None


@dataclass(frozen=True)
class ArchivePublishSummary:
    results: tuple[ArchivePublishResult, ...]
    vault_root: Path


def publish_archive_apks(
    *,
    vault_root: Path,
    repository: str,
    github_token: str,
    body_template_path: Path,
    release_tag: str = DEFAULT_ARCHIVE_RELEASE_TAG,
    release_title: str = DEFAULT_ARCHIVE_RELEASE_TITLE,
    archive_id: str | None = None,
    apk_path: Path | None = None,
    all_archives: bool = False,
    skip_upload: bool = False,
    remove_missing: bool = False,
    force: bool = False,
    client: GitHubReleaseClient | None = None,
) -> ArchivePublishSummary:
    if all_archives and apk_path is not None:
        raise ArchivePublishError("--apk-path cannot be used with --all")
    if not all_archives and not archive_id:
        raise ArchivePublishError("--archive-id is required unless --all is used")
    if remove_missing and not all_archives:
        raise ArchivePublishError("--remove-missing can only be used with --all")

    release_spec = ReleaseSpec(
        repository=repository,
        tag=release_tag,
        title=release_title,
        body_template=body_template_path.read_text(encoding="utf-8"),
    )
    icon_release_spec = _icon_release_spec(repository, vault_root)
    release_client = None if skip_upload else client if client is not None else GitHubReleaseClient(github_token)

    if all_archives:
        results = _publish_all_archives(
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
            _publish_one_archive(
                vault_root=vault_root,
                release_spec=release_spec,
                archive_id=archive_id or "",
                apk_path=apk_path,
                release_client=release_client,
                skip_upload=skip_upload,
                force=force,
                icon_release_spec=icon_release_spec,
            ),
        )

    return ArchivePublishSummary(results=tuple(results), vault_root=vault_root)


def _publish_all_archives(
    *,
    vault_root: Path,
    release_spec: ReleaseSpec,
    release_client: GitHubReleaseClient | None,
    skip_upload: bool,
    remove_missing: bool,
    force: bool,
    icon_release_spec: ReleaseSpec,
) -> tuple[ArchivePublishResult, ...]:
    archive_root = vault_root / "archive"
    archive_ids = {
        path.name
        for path in archive_root.iterdir()
        if path.is_dir() and path.name and not path.name.startswith(".")
    } if archive_root.is_dir() else set()

    results: list[ArchivePublishResult] = []
    published_assets: set[str] = set()
    for current_id in sorted(archive_ids):
        result = _publish_one_archive(
            vault_root=vault_root,
            release_spec=release_spec,
            archive_id=current_id,
            apk_path=None,
            release_client=release_client,
            skip_upload=skip_upload,
            force=force,
            icon_release_spec=icon_release_spec,
        )
        results.append(result)
        if result.asset is not None:
            published_assets.add(result.asset)

    if remove_missing and release_client is not None:
        removed_assets = release_client.prune_assets(
            release_spec,
            published_assets,
            ARCHIVE_APK_EXTENSIONS,
        )
        for asset_name in removed_assets:
            results.append(
                ArchivePublishResult(action="removed unreferenced asset", archive_id="", asset=asset_name)
            )

    return tuple(results)


def _publish_one_archive(
    *,
    vault_root: Path,
    release_spec: ReleaseSpec,
    archive_id: str,
    apk_path: Path | None,
    release_client: GitHubReleaseClient | None,
    skip_upload: bool,
    force: bool,
    icon_release_spec: ReleaseSpec,
) -> ArchivePublishResult:
    apk = _resolve_archive_apk(vault_root, archive_id, apk_path)
    icon_path = extract_source_icon(
        apk,
        archive_id,
        vault_root / "tmp" / "archive-icons",
    )
    icon_digest = sha256_file(icon_path) if icon_path is not None else None
    icon_unchanged = _archive_icon_matches(
        vault_root / "archive.json",
        archive_id,
        icon_path.name if icon_path is not None else None,
        icon_digest,
    )
    if icon_path is not None and icon_digest is not None:
        _update_archive_icon(
            vault_root / "archive.json",
            archive_id,
            icon_path.name,
            icon_digest,
        )
    remote_has_asset = False
    remote_has_icon = False

    if release_client is not None:
        remote_has_asset = apk.name in release_client.release_asset_names(
            release_spec.repository,
            release_spec.tag,
        )
        if force or not remote_has_asset:
            release_client.publish_asset(release_spec, apk, ARCHIVE_APK_EXTENSIONS)
        if icon_path is not None:
            remote_has_icon = icon_path.name in release_client.release_asset_names(
                icon_release_spec.repository,
                icon_release_spec.tag,
            )
            if force or not icon_unchanged or not remote_has_icon:
                release_client.publish_asset(icon_release_spec, icon_path, ICON_EXTENSIONS)

    if skip_upload:
        action = "configured"
    elif remote_has_asset and not force and (
        icon_path is None or (icon_unchanged and remote_has_icon)
    ):
        action = "unchanged"
    elif remote_has_asset:
        action = "updated"
    else:
        action = "uploaded"
    return ArchivePublishResult(
        action=action,
        archive_id=archive_id,
        asset=apk.name,
        icon=icon_path.name if icon_path is not None else None,
    )


def _icon_release_spec(repository: str, vault_root: Path) -> ReleaseSpec:
    template_path = vault_root / "docs" / "app-icons-release.md"
    body = (
        template_path.read_text(encoding="utf-8")
        if template_path.is_file()
        else DEFAULT_ICON_RELEASE_BODY
    )
    return ReleaseSpec(
        repository=repository,
        tag=ICON_RELEASE_TAG,
        title=ICON_RELEASE_TITLE,
        body_template=body,
        asset_extensions=frozenset(ICON_EXTENSIONS),
        empty_asset_message="No application icons published yet.",
    )


def _load_archive_json(path: Path) -> dict:
    if not path.is_file():
        return {"schemaVersion": 1, "generatedAt": "", "apps": []}
    try:
        catalog = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArchivePublishError(f"Could not read archive catalog {path}: {exc}") from exc
    if not isinstance(catalog, dict) or not isinstance(catalog.get("apps"), list):
        raise ArchivePublishError(f"Archive catalog must contain an apps array: {path}")
    return catalog


def _archive_icon_matches(path: Path, archive_id: str, asset: str | None, digest: str | None) -> bool:
    if asset is None or digest is None:
        return True
    catalog = _load_archive_json(path)
    entries = [
        app for app in catalog["apps"]
        if isinstance(app, dict) and app.get("id") == archive_id
    ]
    if len(entries) != 1:
        return False
    icon = entries[0].get("icon")
    return (
        isinstance(icon, dict)
        and icon.get("release") == ICON_RELEASE_TAG
        and icon.get("asset") == asset
        and icon.get("sha256") == digest
    )


def _update_archive_icon(path: Path, archive_id: str, asset: str, digest: str) -> None:
    catalog = _load_archive_json(path)
    entries = [
        app for app in catalog["apps"]
        if isinstance(app, dict) and app.get("id") == archive_id
    ]
    if len(entries) != 1:
        raise ArchivePublishError(
            f"Expected one archive.json entry for {archive_id!r}; found {len(entries)}"
        )
    entries[0]["icon"] = {"release": ICON_RELEASE_TAG, "asset": asset, "sha256": digest}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _resolve_archive_apk(vault_root: Path, archive_id: str, apk_path: Path | None) -> Path:
    if apk_path is not None:
        resolved = apk_path.resolve()
        if not resolved.is_file():
            raise ArchivePublishError(f"Archive APK does not exist: {resolved}")
        if resolved.suffix.lower() not in ARCHIVE_APK_EXTENSIONS:
            raise ArchivePublishError(f"Archive file must be an APK: {resolved}")
        return resolved

    archive_dir = vault_root / "archive" / archive_id
    if not archive_dir.is_dir():
        raise ArchivePublishError(f"Archive directory does not exist: {archive_dir}")

    apks = sorted(
        path for path in archive_dir.iterdir()
        if path.is_file() and path.suffix.lower() in ARCHIVE_APK_EXTENSIONS
    )
    if not apks:
        raise ArchivePublishError(f"No APK found in {archive_dir}")
    if len(apks) > 1:
        raise ArchivePublishError(
            f"Multiple APKs found in {archive_dir}. "
            "Keep exactly one APK or pass --apk-path."
        )
    return apks[0].resolve()


def format_archive_publish_summary(summary: ArchivePublishSummary) -> str:
    lines = [f"Archive sync: {len(summary.results)} result(s)", f"Vault: {summary.vault_root}"]
    for result in summary.results:
        if result.archive_id and result.asset:
            lines.append(f"{result.action}: {result.archive_id} -> {result.asset}")
            if result.icon:
                lines.append(f"  Icon extracted: {result.icon}")
            else:
                lines.append("  Icon extracted: no")
        elif result.asset:
            lines.append(f"{result.action}: {result.asset}")
        else:
            lines.append(f"{result.action}: {result.archive_id}")
    return "\n".join(lines)
