from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from apk_forge.errors import ForgeError

API_ROOT = "https://api.github.com"
USER_AGENT = "APK-Forge"


class ToolDownloadError(ForgeError):
    """Raised when a required build tool cannot be resolved."""


def resolve_morphe_cli(
    workspace_root: Path,
    configured_path: Path | None = None,
    github_token: str | None = None,
) -> Path:
    return resolve_release_tool(
        workspace_root=workspace_root,
        tool_dir_name="morphe-cli",
        repository="MorpheApp/morphe-cli",
        asset_suffix=".jar",
        name_contains=("morphe",),
        name_excludes=("dev",),
        prefer_contains=("-all",),
        configured_path=configured_path,
        github_token=github_token,
    )


def resolve_apkeditor(
    workspace_root: Path,
    configured_path: Path | None = None,
    github_token: str | None = None,
) -> Path:
    return resolve_release_tool(
        workspace_root=workspace_root,
        tool_dir_name="apkeditor",
        repository="REAndroid/APKEditor",
        asset_suffix=".jar",
        name_startswith="apkeditor",
        configured_path=configured_path,
        github_token=github_token,
    )


def resolve_release_tool(
    workspace_root: Path,
    tool_dir_name: str,
    repository: str,
    asset_suffix: str,
    configured_path: Path | None = None,
    github_token: str | None = None,
    name_contains: tuple[str, ...] = (),
    name_excludes: tuple[str, ...] = (),
    name_startswith: str | None = None,
    prefer_contains: tuple[str, ...] = (),
) -> Path:
    if configured_path is not None:
        if not configured_path.is_file():
            raise ToolDownloadError(f"Configured tool does not exist: {configured_path}")
        if configured_path.suffix.lower() != asset_suffix:
            raise ToolDownloadError(f"Configured tool must end with {asset_suffix}: {configured_path}")
        return configured_path

    output_dir = workspace_root / "tools" / tool_dir_name
    output_dir.mkdir(parents=True, exist_ok=True)

    cached = sorted(output_dir.glob(f"*{asset_suffix}"))
    if len(cached) == 1:
        return cached[0]
    if len(cached) > 1:
        raise ToolDownloadError(
            f"Multiple cached {tool_dir_name} tools found in {output_dir}; keep one or pass an explicit path"
        )

    release = github_release(repository, github_token)
    asset = select_release_asset(
        release,
        asset_suffix=asset_suffix,
        name_contains=name_contains,
        name_excludes=name_excludes,
        name_startswith=name_startswith,
        prefer_contains=prefer_contains,
    )
    output_path = output_dir / asset["name"]
    download_asset(asset["url"], output_path, github_token)
    return output_path


def github_release(repository: str, github_token: str | None = None) -> dict:
    request = Request(
        f"{API_ROOT}/repos/{repository}/releases/latest",
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": USER_AGENT,
        },
    )
    if github_token:
        request.add_header("Authorization", f"Bearer {github_token}")

    try:
        with urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise ToolDownloadError(f"Failed to inspect {repository} release: HTTP {exc.code}") from exc
    except URLError as exc:
        raise ToolDownloadError(f"Failed to inspect {repository} release: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise ToolDownloadError(f"Failed to inspect {repository} release: invalid JSON") from exc


def select_release_asset(
    release: dict,
    asset_suffix: str,
    name_contains: tuple[str, ...] = (),
    name_excludes: tuple[str, ...] = (),
    name_startswith: str | None = None,
    prefer_contains: tuple[str, ...] = (),
) -> dict:
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise ToolDownloadError("Tool release response does not contain assets")

    candidates = []
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = asset.get("name")
        url = asset.get("url")
        if not isinstance(name, str) or not isinstance(url, str):
            continue
        lower_name = name.lower()
        if not lower_name.endswith(asset_suffix):
            continue
        if name_startswith is not None and not lower_name.startswith(name_startswith.lower()):
            continue
        if any(part.lower() not in lower_name for part in name_contains):
            continue
        if any(part.lower() in lower_name for part in name_excludes):
            continue
        candidates.append(asset)

    preferred = [
        asset for asset in candidates
        if all(part.lower() in asset["name"].lower() for part in prefer_contains)
    ] if prefer_contains else []
    if len(preferred) == 1:
        return preferred[0]
    if preferred:
        candidates = preferred

    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise ToolDownloadError("No matching tool asset found in latest release")
    names = ", ".join(asset["name"] for asset in candidates)
    raise ToolDownloadError(f"Multiple matching tool assets found: {names}")


def download_asset(download_url: str, output_path: Path, github_token: str | None = None) -> None:
    request = Request(
        download_url,
        headers={
            "Accept": "application/octet-stream",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": USER_AGENT,
        },
    )
    if github_token:
        request.add_header("Authorization", f"Bearer {github_token}")

    try:
        with urlopen(request, timeout=300) as response:
            output_path.write_bytes(response.read())
    except HTTPError as exc:
        raise ToolDownloadError(f"Failed to download tool asset: HTTP {exc.code}") from exc
    except URLError as exc:
        raise ToolDownloadError(f"Failed to download tool asset: {exc.reason}") from exc
