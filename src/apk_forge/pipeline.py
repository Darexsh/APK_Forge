from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from apk_forge.catalog import Catalog
from apk_forge.errors import ForgeError
from apk_forge.models import AppsConfig, PlannedApp
from apk_forge.morphe import patch_apk, prepare_morphe_patch_command
from apk_forge.mpp import compatible_versions, download_mpp
from apk_forge.planner import create_plan
from apk_forge.releases import patched_signed_asset_name, patched_unsigned_asset_name, source_version_name
from apk_forge.signing import (
    prepare_sign_command,
    prepare_verify_command,
    resolve_apksigner,
    resolve_default_keystore,
    sign_apk,
    verify_apk,
)
from apk_forge.source_package import prepare_source_package
from apk_forge.tools import resolve_apkeditor, resolve_morphe_cli


class PipelineError(ForgeError):
    """Raised when the managed-app pipeline cannot run."""


@dataclass(frozen=True)
class DryRunAppResult:
    id: str
    name: str
    package_name: str
    source_path: Path
    source_sha256: str
    catalog_status: str


@dataclass(frozen=True)
class DryRunResult:
    apps: tuple[DryRunAppResult, ...]


@dataclass(frozen=True)
class BuildAppResult:
    id: str
    name: str
    package_name: str
    source_path: Path
    patch_input_apk: Path
    patches_path: Path
    unsigned_apk: Path
    output_apk: Path
    signed: bool
    converted_source: bool


@dataclass(frozen=True)
class BuildFailureResult:
    id: str
    name: str
    package_name: str
    message: str


@dataclass(frozen=True)
class BuildResult:
    apps: tuple[BuildAppResult, ...]
    failures: tuple[BuildFailureResult, ...] = ()


def create_dry_run(
    config: AppsConfig,
    vault_root: Path,
    existing_catalog: Catalog | None = None,
    github_token: str | None = None,
    workspace_root: Path | None = None,
) -> DryRunResult:
    catalog_packages = {
        app.package_name
        for app in existing_catalog.apps
    } if existing_catalog is not None else set()

    results = []
    for planned in create_plan(config, vault_root, github_token, workspace_root):
        catalog_status = (
            "present-in-catalog"
            if planned.app.package_name in catalog_packages
            else "missing-from-catalog"
        )
        results.append(
            DryRunAppResult(
                id=planned.app.id,
                name=planned.app.name,
                package_name=planned.app.package_name,
                source_path=planned.source_path,
                source_sha256=planned.source_sha256,
                catalog_status=catalog_status,
            )
        )

    return DryRunResult(apps=tuple(results))


def run_local_build(
    config: AppsConfig,
    vault_root: Path,
    workspace_root: Path,
    morphe_cli_jar: Path | None = None,
    github_token: str | None = None,
    apkeditor_jar: Path | None = None,
    apksigner: Path | None = None,
    keystore: Path | None = None,
    key_alias: str | None = "public",
    keystore_password: str | None = "public",
    key_password: str | None = "public",
    skip_signing: bool = False,
    continue_on_error: bool = False,
) -> BuildResult:
    results: list[BuildAppResult] = []
    failures: list[BuildFailureResult] = []
    resolved_morphe_cli_jar = resolve_morphe_cli(
        workspace_root,
        morphe_cli_jar,
        github_token,
    )

    for planned in create_plan(config, vault_root, github_token, workspace_root):
        try:
            results.append(
                build_planned_app(
                    planned=planned,
                    vault_root=vault_root,
                    workspace_root=workspace_root,
                    resolved_morphe_cli_jar=resolved_morphe_cli_jar,
                    github_token=github_token,
                    apkeditor_jar=apkeditor_jar,
                    apksigner=apksigner,
                    keystore=keystore,
                    key_alias=key_alias,
                    keystore_password=keystore_password,
                    key_password=key_password,
                    skip_signing=skip_signing,
                )
            )
        except ForgeError as exc:
            if not continue_on_error:
                raise
            failures.append(
                BuildFailureResult(
                    id=planned.app.id,
                    name=planned.app.name,
                    package_name=planned.app.package_name,
                    message=str(exc),
                )
            )

    return BuildResult(apps=tuple(results), failures=tuple(failures))


def build_planned_app(
    *,
    planned: PlannedApp,
    vault_root: Path,
    workspace_root: Path,
    resolved_morphe_cli_jar: Path,
    github_token: str | None = None,
    apkeditor_jar: Path | None = None,
    apksigner: Path | None = None,
    keystore: Path | None = None,
    key_alias: str | None = "public",
    keystore_password: str | None = "public",
    key_password: str | None = "public",
    skip_signing: bool = False,
) -> BuildAppResult:
    resolved_apkeditor_jar = (
        resolve_apkeditor(workspace_root, apkeditor_jar, github_token)
        if planned.source_path.suffix.lower() != ".apk"
        else apkeditor_jar
    )
    app_workspace = workspace_root / "build" / planned.app.id
    prepared = prepare_source_package(
        planned.source_path,
        app_workspace / "prepared",
        resolved_apkeditor_jar,
    )
    patches_path = download_mpp(
        planned.app.mpp,
        app_workspace / "patches",
        github_token,
    )
    validate_mpp_compatibility(
        morphe_cli_jar=resolved_morphe_cli_jar,
        patches=patches_path,
        package_name=planned.app.package_name,
        source_version=source_version_name(planned.source_path),
        app_id=planned.app.id,
    )

    unsigned_apk = app_workspace / "unsigned" / patched_unsigned_asset_name(
        planned.app,
        planned.source_path,
    )
    unsigned_apk.parent.mkdir(parents=True, exist_ok=True)
    patch_command = prepare_morphe_patch_command(
        cli_jar=resolved_morphe_cli_jar,
        patches=patches_path,
        input_apk=prepared.patch_input_apk,
        output_apk=unsigned_apk,
    )
    patch_apk(patch_command)

    signed = not skip_signing
    if signed:
        if key_alias is None:
            raise PipelineError("Signing key alias must not be empty")
        resolved_apksigner = resolve_apksigner(apksigner)
        resolved_keystore = resolve_default_keystore(vault_root, keystore)
        output_apk = app_workspace / "signed" / patched_signed_asset_name(
            planned.app,
            planned.source_path,
        )
        output_apk.parent.mkdir(parents=True, exist_ok=True)
        sign_command = prepare_sign_command(
            apksigner=resolved_apksigner,
            keystore=resolved_keystore,
            key_alias=key_alias,
            input_apk=unsigned_apk,
            output_apk=output_apk,
            keystore_password=keystore_password,
            key_password=key_password,
        )
        sign_apk(sign_command)
        verify_apk(prepare_verify_command(resolved_apksigner, output_apk))
    else:
        output_apk = unsigned_apk

    return BuildAppResult(
        id=planned.app.id,
        name=planned.app.name,
        package_name=planned.app.package_name,
        source_path=planned.source_path,
        patch_input_apk=prepared.patch_input_apk,
        patches_path=patches_path,
        unsigned_apk=unsigned_apk,
        output_apk=output_apk,
        signed=signed,
        converted_source=prepared.converted,
    )


def validate_mpp_compatibility(
    morphe_cli_jar: Path,
    patches: Path,
    package_name: str,
    source_version: str,
    app_id: str,
) -> None:
    versions = compatible_versions(morphe_cli_jar, patches, package_name)
    if source_version in versions:
        return
    if not versions:
        raise PipelineError(
            f"{app_id}: MPP has no compatible versions for {package_name}. "
            "Check the app package name or choose a matching MPP file."
        )
    raise PipelineError(
        f"{app_id}: source APK version {source_version} is not compatible with {patches.name}. "
        f"Compatible versions: {', '.join(versions)}. Update the source APK or choose a matching MPP file."
    )


def format_dry_run(result: DryRunResult) -> str:
    lines = [f"Dry run: {len(result.apps)} enabled app(s)"]
    if not result.apps:
        lines.append("No enabled apps to process.")
        return "\n".join(lines)

    for index, app in enumerate(result.apps, start=1):
        lines.extend(
            [
                "",
                f"{index}. {app.name} ({app.id})",
                f"   Package: {app.package_name}",
                f"   Source package: {app.source_path}",
                f"   Source SHA-256: {app.source_sha256}",
                f"   Patch-ready: {'yes' if app.source_path.suffix.lower() == '.apk' else 'needs conversion'}",
                f"   Catalog: {app.catalog_status}",
                "   Build: not executed in dry-run mode",
            ]
        )

    return "\n".join(lines)


def format_build_result(result: BuildResult) -> str:
    lines = [f"Build: {len(result.apps)} app(s)"]
    if not result.apps and not result.failures:
        lines.append("No enabled apps to process.")
        return "\n".join(lines)

    for index, app in enumerate(result.apps, start=1):
        lines.extend(
            [
                "",
                f"{index}. {app.name} ({app.id})",
                f"   Package: {app.package_name}",
                f"   Source package: {app.source_path}",
                f"   Patch input: {app.patch_input_apk}",
                f"   Source converted: {'yes' if app.converted_source else 'no'}",
                f"   MPP: {app.patches_path}",
                f"   Unsigned APK: {app.unsigned_apk}",
                f"   Output APK: {app.output_apk}",
                f"   Signed: {'yes' if app.signed else 'no'}",
            ]
        )

    if result.failures:
        lines.extend(["", f"Failed: {len(result.failures)} app(s)"])
        for failure in result.failures:
            lines.append(f"- {failure.name} ({failure.id}): {failure.message}")

    return "\n".join(lines)
