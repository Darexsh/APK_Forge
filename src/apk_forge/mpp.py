from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from apk_forge.errors import ForgeError
from apk_forge.models import MppSource
from apk_forge.process import run_process


class MppError(ForgeError):
    """Raised when an .mpp definition cannot be resolved."""


def mpp_raw_url(source: MppSource) -> str:
    if source.path is None:
        raise MppError("Raw MPP URL requires mpp.path")
    return (
        "https://raw.githubusercontent.com/"
        f"{source.owner}/{source.repository}/{source.ref}/{source.path}"
    )


def mpp_release_url(source: MppSource) -> str:
    repo = f"{source.owner}/{source.repository}"
    if source.release == "latest":
        return f"https://api.github.com/repos/{repo}/releases/latest"
    encoded_release = quote(source.release, safe="")
    return f"https://api.github.com/repos/{repo}/releases/tags/{encoded_release}"


def download_mpp(source: MppSource, output_dir: Path, token: str | None = None) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    if source.path is None:
        return download_release_mpp(source, output_dir, token)

    output_path = output_dir / Path(source.path).name
    if output_path.suffix.lower() != ".mpp":
        raise MppError(f"MPP output must end with .mpp: {output_path}")

    request = Request(mpp_raw_url(source))
    if token:
        request.add_header("Authorization", f"Bearer {token}")

    try:
        with urlopen(request, timeout=60) as response:
            output_path.write_bytes(response.read())
    except HTTPError as exc:
        raise MppError(f"Failed to download MPP: HTTP {exc.code}") from exc
    except URLError as exc:
        raise MppError(f"Failed to download MPP: {exc.reason}") from exc

    return output_path


def resolve_mpp_identifier(source: MppSource, token: str | None = None) -> str:
    base = f"{source.owner}/{source.repository}"
    if source.path is not None:
        return f"{base}:{Path(source.path).name}@{source.ref}"
    asset = find_release_mpp_asset(source, token)
    return f"{base}:{asset['name']}@{source.release}"


def download_release_mpp(source: MppSource, output_dir: Path, token: str | None = None) -> Path:
    asset = find_release_mpp_asset(source, token)
    asset_name = asset["name"]
    output_path = output_dir / asset_name
    download_url = asset["url"]

    request = Request(
        download_url,
        headers={
            "Accept": "application/octet-stream",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "APK-Forge",
        },
    )
    if token:
        request.add_header("Authorization", f"Bearer {token}")

    try:
        with urlopen(request, timeout=120) as response:
            output_path.write_bytes(response.read())
    except HTTPError as exc:
        raise MppError(f"Failed to download MPP asset: HTTP {exc.code}") from exc
    except URLError as exc:
        raise MppError(f"Failed to download MPP asset: {exc.reason}") from exc

    return output_path


def find_release_mpp_asset(source: MppSource, token: str | None = None) -> dict:
    release = load_release(source, token)
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise MppError("Release response does not contain assets")

    candidates = [
        asset for asset in assets
        if isinstance(asset, dict)
        and isinstance(asset.get("name"), str)
        and asset["name"].lower().endswith(".mpp")
        and isinstance(asset.get("url"), str)
    ]
    if source.asset is not None:
        candidates = [asset for asset in candidates if asset["name"] == source.asset]

    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise MppError(f"No .mpp release asset found for {source.owner}/{source.repository}@{source.release}")
    raise MppError(
        f"Multiple .mpp release assets found for {source.owner}/{source.repository}@{source.release}; "
        "set mpp.asset to choose one"
    )


def compatible_versions(
    morphe_cli_jar: Path,
    patches: Path,
    package_name: str,
) -> tuple[str, ...]:
    result = run_process(
        [
            "java",
            "-jar",
            str(morphe_cli_jar),
            "list-versions",
            "--patches",
            str(patches),
            "--filter-package-names",
            package_name,
        ]
    )
    return parse_compatible_versions(result.stdout)


def parse_compatible_versions(output: str) -> tuple[str, ...]:
    versions: list[str] = []
    in_versions = False
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line == "Most common compatible versions:":
            in_versions = True
            continue
        if line.startswith("INFO: Package name:"):
            in_versions = False
            continue
        if in_versions:
            version = line.split(" [versionCodes:", 1)[0].split(" (", 1)[0].strip()
            if version:
                versions.append(version)
    return tuple(versions)


def load_release(source: MppSource, token: str | None = None) -> dict:
    request = Request(
        mpp_release_url(source),
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "APK-Forge",
        },
    )
    if token:
        request.add_header("Authorization", f"Bearer {token}")

    try:
        with urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise MppError(f"Failed to inspect MPP release: HTTP {exc.code}") from exc
    except URLError as exc:
        raise MppError(f"Failed to inspect MPP release: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise MppError("Failed to inspect MPP release: invalid JSON") from exc
