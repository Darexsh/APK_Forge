from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from apk_forge.errors import ForgeError
from apk_forge.github_release import GitHubReleaseClient, ReleaseSpec

DEFAULT_ARCHIVE_RELEASE_TAG = "archive-apks"
DEFAULT_ARCHIVE_RELEASE_TITLE = "Archive APKs"
ARCHIVE_APK_EXTENSIONS = {".apk"}


class ArchivePublishError(ForgeError):
    """Raised when archive APK publishing cannot complete."""


@dataclass(frozen=True)
class ArchivePublishResult:
    action: str
    archive_id: str
    asset: str | None = None


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
    release_client = None if skip_upload else client if client is not None else GitHubReleaseClient(github_token)

    if all_archives:
        results = _publish_all_archives(
            vault_root=vault_root,
            release_spec=release_spec,
            release_client=release_client,
            skip_upload=skip_upload,
            remove_missing=remove_missing,
            force=force,
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
) -> ArchivePublishResult:
    apk = _resolve_archive_apk(vault_root, archive_id, apk_path)
    remote_has_asset = False

    if release_client is not None:
        remote_has_asset = apk.name in release_client.release_asset_names(
            release_spec.repository,
            release_spec.tag,
        )
        if force or not remote_has_asset:
            release_client.publish_asset(release_spec, apk, ARCHIVE_APK_EXTENSIONS)

    if skip_upload:
        action = "configured"
    elif remote_has_asset and not force:
        action = "unchanged"
    elif remote_has_asset and force:
        action = "updated"
    else:
        action = "uploaded"
    return ArchivePublishResult(action=action, archive_id=archive_id, asset=apk.name)


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
        elif result.asset:
            lines.append(f"{result.action}: {result.asset}")
        else:
            lines.append(f"{result.action}: {result.archive_id}")
    return "\n".join(lines)
