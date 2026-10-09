from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from apk_forge.errors import SourceApkError
from apk_forge.models import ManagedApp, PlannedApp

SOURCE_PACKAGE_EXTENSIONS = {".apk", ".apkm", ".apks", ".xapk"}


def plan_source_apk(
    app: ManagedApp,
    vault_root: Path,
    github_token: str | None = None,
    workspace_root: Path | None = None,
) -> PlannedApp:
    source_path = _resolve_source_path(app, vault_root, github_token, workspace_root)

    digest = sha256_file(source_path)
    expected = app.source_apk.sha256
    if expected is not None and digest != expected:
        raise SourceApkError(
            f"{app.id}: source APK SHA-256 mismatch. expected {expected}, got {digest}"
        )

    return PlannedApp(app=app, source_path=source_path, source_sha256=digest)


def _resolve_source_path(
    app: ManagedApp,
    vault_root: Path,
    github_token: str | None,
    workspace_root: Path | None,
) -> Path:
    if app.source_apk.type == "githubReleaseAsset":
        if workspace_root is None:
            raise SourceApkError(
                f"{app.id}: githubReleaseAsset sources require a workspace root"
            )
        return download_github_release_asset(app, workspace_root, github_token)

    if app.source_apk.type != "vault":
        raise SourceApkError(f"{app.id}: unsupported source APK type: {app.source_apk.type}")

    configured_path = app.source_apk.resolve(vault_root)
    if configured_path.is_dir():
        apk_files = sorted(
            path for path in configured_path.iterdir()
            if path.is_file() and path.suffix.lower() in SOURCE_PACKAGE_EXTENSIONS
        )
        if len(apk_files) == 1:
            return apk_files[0]
        if not apk_files:
            raise SourceApkError(
                f"{app.id}: source package directory contains no supported files: {configured_path}\n"
                "Add exactly one supported source package to the directory or update "
                f"{app.id}.sourceApk.path in apps.json."
            )
        raise SourceApkError(
            f"{app.id}: source package directory contains multiple supported files: {configured_path}\n"
            "Keep exactly one source package in the directory so Forge does not guess which one to use."
        )

    if not configured_path.is_file():
        raise SourceApkError(
            f"{app.id}: source package does not exist: {configured_path}\n"
            "Add the source package to the private instance repository or update "
            f"{app.id}.sourceApk.path in apps.json."
        )
    if configured_path.suffix.lower() not in SOURCE_PACKAGE_EXTENSIONS:
        raise SourceApkError(
            f"{app.id}: source file must be one of {sorted(SOURCE_PACKAGE_EXTENSIONS)}: {configured_path}"
        )

    return configured_path


def github_release_asset_api_url(repository: str, release: str) -> str:
    owner_repo = repository.strip("/")
    encoded_release = quote(release, safe="")
    return f"https://api.github.com/repos/{owner_repo}/releases/tags/{encoded_release}"


def download_github_release_asset(
    app: ManagedApp,
    workspace_root: Path,
    github_token: str | None,
) -> Path:
    source = app.source_apk
    if source.repository is None or source.release is None or source.asset is None:
        raise SourceApkError(f"{app.id}: githubReleaseAsset source is incomplete")
    if Path(source.asset).suffix.lower() not in SOURCE_PACKAGE_EXTENSIONS:
        raise SourceApkError(
            f"{app.id}: GitHub release asset must be one of {sorted(SOURCE_PACKAGE_EXTENSIONS)}: {source.asset}"
        )

    output_dir = workspace_root / "source-apks" / app.id
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / source.asset

    download_url = _find_github_release_asset_download_url(
        source.repository,
        source.release,
        source.asset,
        github_token,
    )
    request = Request(
        download_url,
        headers={
            "Accept": "application/octet-stream",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "APK-Forge",
        },
    )
    if github_token:
        request.add_header("Authorization", f"Bearer {github_token}")

    try:
        with urlopen(request, timeout=120) as response:
            output_path.write_bytes(response.read())
    except HTTPError as exc:
        raise SourceApkError(
            f"{app.id}: failed to download GitHub release asset: HTTP {exc.code}"
        ) from exc
    except URLError as exc:
        raise SourceApkError(
            f"{app.id}: failed to download GitHub release asset: {exc.reason}"
        ) from exc

    return output_path


def _find_github_release_asset_download_url(
    repository: str,
    release: str,
    asset_name: str,
    github_token: str | None,
) -> str:
    request = Request(
        github_release_asset_api_url(repository, release),
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    if github_token:
        request.add_header("Authorization", f"Bearer {github_token}")

    try:
        with urlopen(request, timeout=60) as response:
            release_data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise SourceApkError(f"Failed to inspect GitHub release: HTTP {exc.code}") from exc
    except URLError as exc:
        raise SourceApkError(f"Failed to inspect GitHub release: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise SourceApkError("Failed to inspect GitHub release: invalid JSON") from exc

    assets = release_data.get("assets")
    if not isinstance(assets, list):
        raise SourceApkError("Failed to inspect GitHub release: missing assets list")

    for asset in assets:
        if not isinstance(asset, dict):
            continue
        if asset.get("name") == asset_name:
            download_url = asset.get("url")
            if not isinstance(download_url, str) or not download_url:
                raise SourceApkError(f"GitHub release asset has no API download URL: {asset_name}")
            return download_url

    raise SourceApkError(f"GitHub release asset not found: {asset_name}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
