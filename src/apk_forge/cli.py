from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from apk_forge.catalog import Catalog, load_catalog, write_catalog
from apk_forge.config import load_apps_config
from apk_forge.errors import ForgeError
from apk_forge.github_release import GitHubReleaseClient, ReleaseSpec
from apk_forge.morphe import prepare_morphe_patch_command
from apk_forge.mpp import download_mpp, mpp_raw_url, mpp_release_url
from apk_forge.output import format_plan
from apk_forge.pipeline import create_dry_run, format_build_result, format_dry_run, run_local_build
from apk_forge.planner import create_plan
from apk_forge.publish import format_publish_result, publish_from_paths
from apk_forge.signing import prepare_sign_command, prepare_verify_command
from apk_forge.source_apk import sha256_file
from apk_forge.source_publish import format_source_publish_summary, publish_source_packages
from apk_forge.sync import format_sync_result, sync_from_paths


def main(argv: list[str] | None = None) -> int:
    _load_env_file(Path(".env"))
    parser = _build_parser()
    args = parser.parse_args(argv)
    vault_root = getattr(args, "vault_root", None)
    if isinstance(vault_root, Path):
        _load_env_file(vault_root / ".env")

    try:
        if args.command == "validate":
            return _validate(args)
        if args.command == "plan":
            return _plan(args)
        if args.command == "hash":
            return _hash(args)
        if args.command == "catalog":
            return _catalog(args)
        if args.command == "run":
            return _run(args)
        if args.command == "morphe":
            return _morphe(args)
        if args.command == "mpp":
            return _mpp(args)
        if args.command == "signing":
            return _signing(args)
        if args.command == "release":
            return _release(args)
        if args.command == "source":
            return _source(args)
        if args.command == "publish":
            return _publish(args)
        if args.command == "sync":
            return _sync(args)
    except ForgeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    parser.print_help()
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="apk-forge")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="validate an apps.json file")
    validate.add_argument("--config", required=True, type=Path)

    plan = subparsers.add_parser("plan", help="create a managed-app processing plan")
    plan.add_argument("--config", required=True, type=Path)
    plan.add_argument("--vault-root", required=True, type=Path)
    plan.add_argument("--workspace-root", type=Path)
    plan.add_argument("--github-token")
    plan.add_argument("--json", action="store_true", help="print machine-readable JSON")

    hash_command = subparsers.add_parser("hash", help="print the SHA-256 digest for a source package")
    hash_command.add_argument("source_package", type=Path)

    catalog = subparsers.add_parser("catalog", help="manage catalog.json files")
    catalog_subparsers = catalog.add_subparsers(dest="catalog_command", required=True)

    catalog_init = catalog_subparsers.add_parser("init", help="write an empty catalog.json")
    catalog_init.add_argument("--output", required=True, type=Path)

    catalog_validate = catalog_subparsers.add_parser("validate", help="validate a catalog.json file")
    catalog_validate.add_argument("--catalog", required=True, type=Path)

    run = subparsers.add_parser("run", help="run the managed-app pipeline")
    run.add_argument("--config", required=True, type=Path)
    run.add_argument("--vault-root", required=True, type=Path)
    run.add_argument("--catalog", type=Path)
    run.add_argument("--workspace-root", type=Path)
    run.add_argument("--github-token")
    run_mode = run.add_mutually_exclusive_group(required=True)
    run_mode.add_argument("--dry-run", action="store_true")
    run_mode.add_argument("--execute", action="store_true", help="patch locally instead of only planning")
    run.add_argument("--morphe-cli-jar", type=Path, help="optional local Morphe CLI jar override")
    run.add_argument("--apkeditor-jar", type=Path, help="optional local APKEditor jar override")
    run.add_argument("--apksigner", type=Path)
    run.add_argument("--keystore", type=Path)
    run.add_argument("--key-alias", default="public")
    run.add_argument("--keystore-password", default="public")
    run.add_argument("--key-password", default="public")
    run.add_argument("--skip-signing", action="store_true")
    run.add_argument("--json", action="store_true", help="print machine-readable JSON")

    morphe = subparsers.add_parser("morphe", help="Morphe helper commands")
    morphe_subparsers = morphe.add_subparsers(dest="morphe_command", required=True)

    morphe_command = morphe_subparsers.add_parser("command", help="print a Morphe patch command")
    morphe_command.add_argument("--cli-jar", required=True, type=Path)
    morphe_command.add_argument("--patches", required=True, type=Path)
    morphe_command.add_argument("--input-apk", required=True, type=Path)
    morphe_command.add_argument("--output-apk", required=True, type=Path)
    morphe_command.add_argument("--include-patch", action="append", default=[])
    morphe_command.add_argument("--exclude-patch", action="append", default=[])

    morphe_run = morphe_subparsers.add_parser("run", help="run a Morphe patch command")
    morphe_run.add_argument("--cli-jar", required=True, type=Path)
    morphe_run.add_argument("--patches", required=True, type=Path)
    morphe_run.add_argument("--input-apk", required=True, type=Path)
    morphe_run.add_argument("--output-apk", required=True, type=Path)
    morphe_run.add_argument("--include-patch", action="append", default=[])
    morphe_run.add_argument("--exclude-patch", action="append", default=[])

    mpp = subparsers.add_parser("mpp", help="MPP helper commands")
    mpp_subparsers = mpp.add_subparsers(dest="mpp_command", required=True)

    mpp_url = mpp_subparsers.add_parser("url", help="print the raw MPP download URL for an app")
    mpp_url.add_argument("--config", required=True, type=Path)
    mpp_url.add_argument("--app-id", required=True)

    mpp_download = mpp_subparsers.add_parser("download", help="download an app MPP file")
    mpp_download.add_argument("--config", required=True, type=Path)
    mpp_download.add_argument("--app-id", required=True)
    mpp_download.add_argument("--output-dir", required=True, type=Path)
    mpp_download.add_argument("--token")

    signing = subparsers.add_parser("signing", help="APK signing helper commands")
    signing_subparsers = signing.add_subparsers(dest="signing_command", required=True)

    signing_sign = signing_subparsers.add_parser("sign-command", help="print an apksigner sign command")
    signing_sign.add_argument("--apksigner", required=True, type=Path)
    signing_sign.add_argument("--keystore", required=True, type=Path)
    signing_sign.add_argument("--key-alias", required=True)
    signing_sign.add_argument("--input-apk", required=True, type=Path)
    signing_sign.add_argument("--output-apk", required=True, type=Path)

    signing_verify = signing_subparsers.add_parser("verify-command", help="print an apksigner verify command")
    signing_verify.add_argument("--apksigner", required=True, type=Path)
    signing_verify.add_argument("--apk", required=True, type=Path)

    release = subparsers.add_parser("release", help="GitHub release helper commands")
    release_subparsers = release.add_subparsers(dest="release_command", required=True)

    release_sync = release_subparsers.add_parser("sync", help="create/update release title and notes")
    release_sync.add_argument("--repo", required=True)
    release_sync.add_argument("--tag", required=True)
    release_sync.add_argument("--title", required=True)
    release_sync.add_argument("--body-template", required=True, type=Path)
    release_sync.add_argument("--github-token")

    source = subparsers.add_parser("source", help="manage source package release assets")
    source_subparsers = source.add_subparsers(dest="source_command", required=True)

    source_publish = source_subparsers.add_parser(
        "publish",
        help="publish source packages and update apps.json",
    )
    source_publish.add_argument("--config", required=True, type=Path)
    source_publish.add_argument("--vault-root", required=True, type=Path)
    source_publish.add_argument("--repo", required=True)
    source_publish.add_argument("--body-template", required=True, type=Path)
    source_publish.add_argument("--release-tag", default="source-apks")
    source_publish.add_argument("--release-title", default="Source APKs")
    source_publish.add_argument("--app-id")
    source_publish.add_argument("--apk-path", type=Path)
    source_publish.add_argument("--github-token")
    source_publish.add_argument("--all", action="store_true", help="sync every configured app from sources/<app-id>/")
    source_publish.add_argument(
        "--remove-missing",
        action="store_true",
        help="with --all, remove apps from apps.json when sources/<app-id>/ is missing",
    )
    source_publish.add_argument("--skip-upload", action="store_true")
    source_publish.add_argument("--force", action="store_true", help="upload even when asset name and SHA are unchanged")

    publish = subparsers.add_parser("publish", help="publish signed workspace APKs")
    publish.add_argument("--config", required=True, type=Path)
    publish.add_argument("--vault-root", required=True, type=Path)
    publish.add_argument("--workspace-root", required=True, type=Path)
    publish.add_argument("--catalog", required=True, type=Path)
    publish.add_argument("--repo", required=True)
    publish.add_argument("--release-tag", default="patched-apks")
    publish.add_argument("--release-title", default="Patched APKs")
    publish.add_argument("--body-template", required=True, type=Path)
    publish.add_argument("--github-token")

    sync = subparsers.add_parser("sync", help="build, sign, publish, and update catalog")
    sync.add_argument("--config", required=True, type=Path)
    sync.add_argument("--vault-root", required=True, type=Path)
    sync.add_argument("--workspace-root", required=True, type=Path)
    sync.add_argument("--catalog", required=True, type=Path)
    sync.add_argument("--repo", required=True)
    sync.add_argument("--release-tag", default="patched-apks")
    sync.add_argument("--release-title", default="Patched APKs")
    sync.add_argument("--body-template", required=True, type=Path)
    sync.add_argument("--github-token")
    sync.add_argument("--morphe-cli-jar", type=Path, help="optional local Morphe CLI jar override")
    sync.add_argument("--apkeditor-jar", type=Path, help="optional local APKEditor jar override")
    sync.add_argument("--apksigner", type=Path)
    sync.add_argument("--keystore", type=Path)
    sync.add_argument("--key-alias", default="public")
    sync.add_argument("--keystore-password", default="public")
    sync.add_argument("--key-password", default="public")
    sync.add_argument("--force", action="store_true", help="build and publish even when catalog/release look unchanged")

    return parser


def _validate(args: argparse.Namespace) -> int:
    config = load_apps_config(args.config)
    print(f"valid apps.json: {len(config.apps)} app(s), {len(config.enabled_apps)} enabled")
    return 0


def _plan(args: argparse.Namespace) -> int:
    config = load_apps_config(args.config)
    planned_apps = create_plan(
        config,
        args.vault_root,
        _github_token(args),
        args.workspace_root,
    )

    if args.json:
        print(
            json.dumps(
                {
                    "apps": [
                        {
                            "id": planned.app.id,
                            "name": planned.app.name,
                            "packageName": planned.app.package_name,
                            "sourceApk": str(planned.source_path),
                            "sourceSha256": planned.source_sha256,
                            "mpp": {
                                "owner": planned.app.mpp.owner,
                                "repository": planned.app.mpp.repository,
                                "path": planned.app.mpp.path,
                                "ref": planned.app.mpp.ref,
                                "release": planned.app.mpp.release,
                                "asset": planned.app.mpp.asset,
                            },
                            "releasePrefix": planned.app.output.release_prefix,
                        }
                        for planned in planned_apps
                    ]
                },
                indent=2,
            )
        )
        return 0

    print(format_plan(planned_apps))
    return 0


def _hash(args: argparse.Namespace) -> int:
    from apk_forge.source_apk import SOURCE_PACKAGE_EXTENSIONS

    source_path = args.source_package
    if not source_path.is_file():
        print(f"error: source package does not exist: {source_path}", file=sys.stderr)
        return 1
    if source_path.suffix.lower() not in SOURCE_PACKAGE_EXTENSIONS:
        print(f"error: file must be one of {sorted(SOURCE_PACKAGE_EXTENSIONS)}: {source_path}", file=sys.stderr)
        return 1

    print(sha256_file(source_path))
    return 0


def _catalog(args: argparse.Namespace) -> int:
    if args.catalog_command == "init":
        write_catalog(Catalog.empty(), args.output)
        print(f"wrote empty catalog: {args.output}")
        return 0

    if args.catalog_command == "validate":
        catalog = load_catalog(args.catalog)
        print(f"valid catalog.json: {len(catalog.apps)} app(s)")
        return 0

    return 2


def _run(args: argparse.Namespace) -> int:
    config = load_apps_config(args.config)
    catalog = load_catalog(args.catalog) if args.catalog is not None else None
    if args.dry_run:
        result = create_dry_run(
            config,
            args.vault_root,
            catalog,
            _github_token(args),
            args.workspace_root,
        )

        if args.json:
            print(
                json.dumps(
                    {
                        "apps": [
                            {
                                "id": app.id,
                                "name": app.name,
                                "packageName": app.package_name,
                                "sourceApk": str(app.source_path),
                                "sourceSha256": app.source_sha256,
                                "catalogStatus": app.catalog_status,
                                "build": "not-executed-dry-run",
                            }
                            for app in result.apps
                        ]
                    },
                    indent=2,
                )
            )
            return 0

        print(format_dry_run(result))
        return 0

    workspace_root = args.workspace_root
    if workspace_root is None:
        print("error: --workspace-root is required with --execute", file=sys.stderr)
        return 1
    result = run_local_build(
        config=config,
        vault_root=args.vault_root,
        workspace_root=workspace_root,
        morphe_cli_jar=args.morphe_cli_jar,
        github_token=_github_token(args),
        apkeditor_jar=args.apkeditor_jar,
        apksigner=args.apksigner,
        keystore=args.keystore,
        key_alias=args.key_alias,
        keystore_password=args.keystore_password,
        key_password=args.key_password,
        skip_signing=args.skip_signing,
    )

    if args.json:
        print(
            json.dumps(
                {
                    "apps": [
                        {
                            "id": app.id,
                            "name": app.name,
                            "packageName": app.package_name,
                            "sourceApk": str(app.source_path),
                            "patchInputApk": str(app.patch_input_apk),
                            "patches": str(app.patches_path),
                            "unsignedApk": str(app.unsigned_apk),
                            "outputApk": str(app.output_apk),
                            "signed": app.signed,
                            "convertedSource": app.converted_source,
                            "build": "executed-local",
                        }
                        for app in result.apps
                    ]
                },
                indent=2,
            )
        )
        return 0

    print(format_build_result(result))
    return 0


def _github_token(args: argparse.Namespace) -> str | None:
    return args.github_token or os.environ.get("GITHUB_TOKEN")


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _morphe(args: argparse.Namespace) -> int:
    from apk_forge.morphe import patch_apk

    if args.morphe_command == "command":
        command = prepare_morphe_patch_command(
            cli_jar=args.cli_jar,
            patches=args.patches,
            input_apk=args.input_apk,
            output_apk=args.output_apk,
            include_patches=tuple(args.include_patch),
            exclude_patches=tuple(args.exclude_patch),
        )
        print(" ".join(command.as_args()))
        return 0

    if args.morphe_command == "run":
        command = prepare_morphe_patch_command(
            cli_jar=args.cli_jar,
            patches=args.patches,
            input_apk=args.input_apk,
            output_apk=args.output_apk,
            include_patches=tuple(args.include_patch),
            exclude_patches=tuple(args.exclude_patch),
        )
        result = patch_apk(command)
        if result.stdout.strip():
            print(result.stdout.strip())
        if result.stderr.strip():
            print(result.stderr.strip(), file=sys.stderr)
        print(f"patched APK: {command.output_apk}")
        return 0

    return 2


def _mpp(args: argparse.Namespace) -> int:
    config = load_apps_config(args.config)
    app = next((candidate for candidate in config.apps if candidate.id == args.app_id), None)
    if app is None:
        print(f"error: app id not found: {args.app_id}", file=sys.stderr)
        return 1

    if args.mpp_command == "url":
        print(mpp_raw_url(app.mpp) if app.mpp.path else mpp_release_url(app.mpp))
        return 0

    if args.mpp_command == "download":
        path = download_mpp(app.mpp, args.output_dir, args.token)
        print(f"downloaded MPP: {path}")
        return 0

    return 2


def _signing(args: argparse.Namespace) -> int:
    if args.signing_command == "sign-command":
        command = prepare_sign_command(
            apksigner=args.apksigner,
            keystore=args.keystore,
            key_alias=args.key_alias,
            input_apk=args.input_apk,
            output_apk=args.output_apk,
        )
        print(" ".join(command.as_args()))
        return 0

    if args.signing_command == "verify-command":
        command = prepare_verify_command(args.apksigner, args.apk)
        print(" ".join(command.as_args()))
        return 0

    return 2


def _release(args: argparse.Namespace) -> int:
    if args.release_command == "sync":
        body_template = args.body_template.read_text(encoding="utf-8")
        client = GitHubReleaseClient(_github_token(args) or "")
        client.ensure_release(
            ReleaseSpec(
                repository=args.repo,
                tag=args.tag,
                title=args.title,
                body_template=body_template,
            )
        )
        print(f"synced release: {args.repo}/{args.tag}")
        return 0

    return 2


def _source(args: argparse.Namespace) -> int:
    if args.source_command == "publish":
        result = publish_source_packages(
            config_path=args.config,
            vault_root=args.vault_root,
            repository=args.repo,
            github_token=_github_token(args) or "",
            body_template_path=args.body_template,
            release_tag=args.release_tag,
            release_title=args.release_title,
            app_id=args.app_id,
            source_package_path=args.apk_path,
            all_apps=args.all,
            skip_upload=args.skip_upload,
            remove_missing=args.remove_missing,
            force=args.force,
        )
        print(format_source_publish_summary(result))
        return 0

    return 2


def _publish(args: argparse.Namespace) -> int:
    result = publish_from_paths(
        config_path=args.config,
        vault_root=args.vault_root,
        workspace_root=args.workspace_root,
        catalog_path=args.catalog,
        repository=args.repo,
        github_token=_github_token(args) or "",
        body_template_path=args.body_template,
        release_tag=args.release_tag,
        release_title=args.release_title,
    )
    print(format_publish_result(result))
    return 0


def _sync(args: argparse.Namespace) -> int:
    result = sync_from_paths(
        config_path=args.config,
        vault_root=args.vault_root,
        workspace_root=args.workspace_root,
        catalog_path=args.catalog,
        repository=args.repo,
        github_token=_github_token(args) or "",
        body_template_path=args.body_template,
        release_tag=args.release_tag,
        release_title=args.release_title,
        morphe_cli_jar=args.morphe_cli_jar,
        apkeditor_jar=args.apkeditor_jar,
        apksigner=args.apksigner,
        keystore=args.keystore,
        key_alias=args.key_alias,
        keystore_password=args.keystore_password,
        key_password=args.key_password,
        force=args.force,
    )
    print(format_sync_result(result))
    return 0
