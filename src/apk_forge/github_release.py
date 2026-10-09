from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from apk_forge.errors import ForgeError

ASSET_LIST_START = "<!-- APK_FORGE_ASSET_LIST_START -->"
ASSET_LIST_END = "<!-- APK_FORGE_ASSET_LIST_END -->"
API_ROOT = "https://api.github.com"
SOURCE_PACKAGE_EXTENSIONS = {".apk", ".apkm", ".apks", ".xapk"}


class GitHubReleaseError(ForgeError):
    """Raised when a GitHub release operation fails."""


@dataclass(frozen=True)
class ReleaseSpec:
    repository: str
    tag: str
    title: str
    body_template: str


def inject_asset_list(template: str, assets: list[dict]) -> str:
    asset_list = format_asset_list(assets)
    if ASSET_LIST_START not in template or ASSET_LIST_END not in template:
        return "\n".join([template.rstrip(), "", ASSET_LIST_START, asset_list, ASSET_LIST_END, ""])

    before, rest = template.split(ASSET_LIST_START, 1)
    _, after = rest.split(ASSET_LIST_END, 1)
    return f"{before}{ASSET_LIST_START}\n{asset_list}\n{ASSET_LIST_END}{after}"


def format_asset_list(assets: list[dict]) -> str:
    apk_assets = sorted(
        (
            asset for asset in assets
            if Path(str(asset.get("name", ""))).suffix.lower() in SOURCE_PACKAGE_EXTENSIONS
        ),
        key=lambda asset: str(asset.get("name", "")).lower(),
    )
    if not apk_assets:
        return "- _No source package assets listed yet._"
    return "\n".join(f"- `{asset['name']}`" for asset in apk_assets)


class GitHubReleaseClient:
    def __init__(self, token: str) -> None:
        if not token:
            raise GitHubReleaseError("GitHub token missing")
        self.token = token

    def publish_asset(
        self,
        spec: ReleaseSpec,
        apk: Path,
        allowed_extensions: set[str] | None = None,
    ) -> dict:
        allowed = allowed_extensions or {".apk"}
        if apk.suffix.lower() not in allowed:
            raise GitHubReleaseError(f"Release asset must be one of {sorted(allowed)}: {apk}")
        if not apk.is_file():
            raise GitHubReleaseError(f"Release asset does not exist: {apk}")

        release = self.ensure_release(spec)
        self.remove_existing_asset(spec.repository, release, apk.name)
        self.upload_release_asset(release, apk)
        refreshed = self.get_release(spec.repository, spec.tag)
        self.update_release_metadata(spec, refreshed)
        return self.get_release(spec.repository, spec.tag)

    def ensure_release(self, spec: ReleaseSpec) -> dict:
        try:
            release = self.get_release(spec.repository, spec.tag)
            return self.update_release_metadata(spec, release)
        except GitHubReleaseError as exc:
            if "HTTP 404" not in str(exc):
                raise

        body = {
            "tag_name": spec.tag,
            "name": spec.title,
            "body": inject_asset_list(spec.body_template, []),
            "draft": False,
            "prerelease": False,
            "make_latest": "false",
        }
        return self.github_json("POST", f"{API_ROOT}/repos/{spec.repository}/releases", body)

    def get_release(self, repository: str, tag: str) -> dict:
        encoded_tag = quote(tag, safe="")
        return self.github_json("GET", f"{API_ROOT}/repos/{repository}/releases/tags/{encoded_tag}")

    def release_asset_names(self, repository: str, tag: str) -> set[str]:
        try:
            release = self.get_release(repository, tag)
        except GitHubReleaseError as exc:
            if "HTTP 404" in str(exc):
                return set()
            raise
        assets = release.get("assets", [])
        if not isinstance(assets, list):
            return set()
        return {
            asset["name"] for asset in assets
            if isinstance(asset, dict) and isinstance(asset.get("name"), str)
        }

    def update_release_metadata(self, spec: ReleaseSpec, release: dict) -> dict:
        wanted_body = inject_asset_list(spec.body_template, release.get("assets", []))
        if (release.get("name") or "") == spec.title and (release.get("body") or "") == wanted_body:
            return release

        release_id = release.get("id")
        if release_id is None:
            raise GitHubReleaseError(f"GitHub release has no id: {spec.tag}")

        body = {
            "name": spec.title,
            "body": wanted_body,
            "draft": False,
            "prerelease": False,
            "make_latest": "false",
        }
        return self.github_json("PATCH", f"{API_ROOT}/repos/{spec.repository}/releases/{release_id}", body)

    def remove_existing_asset(self, repository: str, release: dict, asset_name: str) -> None:
        for asset in release.get("assets", []):
            if asset.get("name") == asset_name:
                self.github_json("DELETE", f"{API_ROOT}/repos/{repository}/releases/assets/{asset.get('id')}")

    def remove_asset_by_name(self, spec: ReleaseSpec, asset_name: str) -> bool:
        try:
            release = self.get_release(spec.repository, spec.tag)
        except GitHubReleaseError as exc:
            if "HTTP 404" in str(exc):
                return False
            raise

        removed = False
        for asset in release.get("assets", []):
            if asset.get("name") == asset_name:
                self.github_json("DELETE", f"{API_ROOT}/repos/{spec.repository}/releases/assets/{asset.get('id')}")
                removed = True

        if removed:
            refreshed = self.get_release(spec.repository, spec.tag)
            self.update_release_metadata(spec, refreshed)
        return removed

    def prune_assets(
        self,
        spec: ReleaseSpec,
        keep_names: set[str],
        allowed_extensions: set[str] | None = None,
    ) -> tuple[str, ...]:
        allowed = allowed_extensions or SOURCE_PACKAGE_EXTENSIONS
        try:
            release = self.get_release(spec.repository, spec.tag)
        except GitHubReleaseError as exc:
            if "HTTP 404" in str(exc):
                return ()
            raise

        removed: list[str] = []
        for asset in release.get("assets", []):
            asset_name = asset.get("name")
            if not isinstance(asset_name, str):
                continue
            if Path(asset_name).suffix.lower() not in allowed:
                continue
            if asset_name in keep_names:
                continue
            self.github_json("DELETE", f"{API_ROOT}/repos/{spec.repository}/releases/assets/{asset.get('id')}")
            removed.append(asset_name)

        if removed:
            refreshed = self.get_release(spec.repository, spec.tag)
            self.update_release_metadata(spec, refreshed)
        return tuple(sorted(removed))

    def upload_release_asset(self, release: dict, apk: Path) -> None:
        upload_url = release["upload_url"].replace("{?name,label}", "")
        asset_name = quote(apk.name)
        request = Request(
            f"{upload_url}?name={asset_name}",
            method="POST",
            data=apk.read_bytes(),
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/vnd.android.package-archive",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "APK-Forge",
            },
        )
        try:
            with urlopen(request, timeout=300) as response:
                response.read()
        except HTTPError as exc:
            raise GitHubReleaseError(f"GitHub upload failed: HTTP {exc.code} {read_error(exc)}") from exc
        except URLError as exc:
            raise GitHubReleaseError(f"GitHub upload failed: {exc.reason}") from exc

    def github_json(self, method: str, url: str, body: dict | None = None) -> dict:
        data = None
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "APK-Forge",
        }
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(url, method=method, data=data, headers=headers)
        try:
            with urlopen(request, timeout=120) as response:
                content = response.read()
        except HTTPError as exc:
            raise GitHubReleaseError(f"GitHub API failed: HTTP {exc.code} {read_error(exc)}") from exc
        except URLError as exc:
            raise GitHubReleaseError(f"GitHub API failed: {exc.reason}") from exc

        if not content:
            return {}
        return json.loads(content.decode("utf-8"))


def read_error(exc: HTTPError) -> str:
    try:
        return exc.read().decode("utf-8")
    except Exception:
        return ""
