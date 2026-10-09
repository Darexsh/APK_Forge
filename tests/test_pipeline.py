from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apk_forge.catalog import Catalog, CatalogApp
from apk_forge.config import parse_apps_config
from apk_forge.process import ProcessResult
from apk_forge.pipeline import (
    PipelineError,
    create_dry_run,
    format_build_result,
    format_dry_run,
    run_local_build,
    validate_mpp_compatibility,
)


class PipelineTest(unittest.TestCase):
    def test_dry_run_reports_catalog_presence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            vault_root = Path(temp_dir)
            source = vault_root / "example.apk"
            source.write_bytes(b"fake apk")
            config = parse_apps_config(
                {
                    "schemaVersion": 1,
                    "apps": [
                        {
                            "id": "example-app",
                            "name": "Example App",
                            "packageName": "com.example.app",
                            "enabled": True,
                            "mpp": {
                                "owner": "example",
                                "repository": "patches",
                                "path": "example.mpp",
                            },
                            "sourceApk": {
                                "type": "vault",
                                "path": "example.apk",
                            },
                        }
                    ],
                }
            )
            catalog = Catalog(
                schema_version=1,
                generated_at="2026-10-08T00:00:00+00:00",
                apps=(
                    CatalogApp(
                        id="example-app",
                        name="Example App",
                        package_name="com.example.app",
                        version_name="1.0.0",
                        version_code=1,
                        type="managed",
                        release="managed-example-app-1.0.0",
                        asset="example.apk",
                        sha256="a" * 64,
                    ),
                ),
            )

            result = create_dry_run(config, vault_root, catalog)

        self.assertEqual("present-in-catalog", result.apps[0].catalog_status)
        self.assertIn("Build: not executed", format_dry_run(result))

    def test_local_build_patches_without_signing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            vault_root = root / "vault"
            vault_root.mkdir()
            workspace_root = root / "workspace"
            source = vault_root / "example.apk"
            source.write_bytes(b"fake apk")
            patches = root / "example.mpp"
            patches.write_bytes(b"patches")
            config = _config_for_source("example.apk")

            def fake_patch(command) -> ProcessResult:
                command.output_apk.write_bytes(b"patched")
                return ProcessResult(args=tuple(command.as_args()), return_code=0, stdout="", stderr="")

            with (
                patch("apk_forge.pipeline.resolve_morphe_cli", return_value=root / "morphe-cli.jar"),
                patch("apk_forge.pipeline.download_mpp", return_value=patches),
                patch("apk_forge.pipeline.compatible_versions", return_value=("unknown",)),
                patch("apk_forge.pipeline.patch_apk", side_effect=fake_patch) as patch_apk,
            ):
                result = run_local_build(
                    config=config,
                    vault_root=vault_root,
                    workspace_root=workspace_root,
                    morphe_cli_jar=root / "morphe-cli.jar",
                    skip_signing=True,
                )
                output_bytes = result.apps[0].output_apk.read_bytes()

            self.assertEqual(1, patch_apk.call_count)
            self.assertFalse(result.apps[0].signed)
            self.assertEqual(b"patched", output_bytes)
            self.assertIn("Signed: no", format_build_result(result))

    def test_local_build_signs_and_verifies(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            vault_root = root / "vault"
            vault_root.mkdir()
            workspace_root = root / "workspace"
            source = vault_root / "example.apk"
            source.write_bytes(b"fake apk")
            patches = root / "example.mpp"
            patches.write_bytes(b"patches")
            config = _config_for_source("example.apk")

            def fake_patch(command) -> ProcessResult:
                command.output_apk.write_bytes(b"unsigned")
                return ProcessResult(args=tuple(command.as_args()), return_code=0, stdout="", stderr="")

            def fake_sign(command) -> ProcessResult:
                command.output_apk.write_bytes(b"signed")
                return ProcessResult(args=tuple(command.as_args()), return_code=0, stdout="", stderr="")

            with (
                patch("apk_forge.pipeline.resolve_morphe_cli", return_value=root / "morphe-cli.jar"),
                patch("apk_forge.pipeline.download_mpp", return_value=patches),
                patch("apk_forge.pipeline.compatible_versions", return_value=("unknown",)),
                patch("apk_forge.pipeline.patch_apk", side_effect=fake_patch),
                patch("apk_forge.pipeline.resolve_apksigner", return_value=root / "apksigner"),
                patch("apk_forge.pipeline.resolve_default_keystore", return_value=root / "signing.jks"),
                patch("apk_forge.pipeline.sign_apk", side_effect=fake_sign) as sign_apk,
                patch("apk_forge.pipeline.verify_apk") as verify_apk,
            ):
                result = run_local_build(
                    config=config,
                    vault_root=vault_root,
                    workspace_root=workspace_root,
                )
                output_bytes = result.apps[0].output_apk.read_bytes()

            self.assertEqual(1, sign_apk.call_count)
            self.assertEqual(1, verify_apk.call_count)
            self.assertTrue(result.apps[0].signed)
            self.assertEqual(b"signed", output_bytes)

    def test_rejects_incompatible_mpp_version(self) -> None:
        with patch("apk_forge.pipeline.compatible_versions", return_value=("1.2.4",)):
            with self.assertRaisesRegex(PipelineError, "Update the source APK"):
                validate_mpp_compatibility(
                    morphe_cli_jar=Path("morphe.jar"),
                    patches=Path("patches-1.22.1.mpp"),
                    package_name="com.example.app",
                    source_version="1.2.3",
                    app_id="example",
                )


def _config_for_source(source_path: str):
    return parse_apps_config(
        {
            "schemaVersion": 1,
            "apps": [
                {
                    "id": "example-app",
                    "name": "Example App",
                    "packageName": "com.example.app",
                    "enabled": True,
                    "mpp": {
                        "owner": "example",
                        "repository": "patches",
                        "path": "example.mpp",
                    },
                    "sourceApk": {
                        "type": "vault",
                        "path": source_path,
                    },
                }
            ],
        }
    )


if __name__ == "__main__":
    unittest.main()
