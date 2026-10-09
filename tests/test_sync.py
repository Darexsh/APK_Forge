from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apk_forge.catalog import CatalogApp
from apk_forge.config import parse_apps_config
from apk_forge.planner import create_plan
from apk_forge.pipeline import BuildAppResult, BuildFailureResult, BuildResult
from apk_forge.publish import PublishResult
from apk_forge.sync import format_sync_result, is_planned_app_unchanged, sync_build_and_publish


class SyncTest(unittest.TestCase):
    def test_sync_builds_then_publishes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = parse_apps_config(
                {
                    "schemaVersion": 1,
                    "apps": [
                        {
                            "id": "example",
                            "name": "Example",
                            "packageName": "com.example",
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
            build_result = BuildResult(apps=())
            publish_result = PublishResult(apps=(), catalog_path=root / "catalog.json")

            with (
                patch("apk_forge.sync.filter_unchanged_apps", return_value=(config, ())),
                patch("apk_forge.sync.run_local_build", return_value=build_result) as build,
                patch("apk_forge.sync.publish_signed_workspace_outputs", return_value=publish_result) as publish,
            ):
                result = sync_build_and_publish(
                    config=config,
                    vault_root=root / "vault",
                    workspace_root=root / "workspace",
                    catalog_path=root / "catalog.json",
                    repository="owner/repo",
                    github_token="token",
                    body_template_path=root / "body.md",
                )

        self.assertEqual(build_result, result.build)
        self.assertEqual(publish_result, result.publish)
        self.assertEqual(1, build.call_count)
        self.assertEqual(1, publish.call_count)
        self.assertIn("Build completed", format_sync_result(result))

    def test_sync_skips_unchanged_planned_app(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            vault_root = root / "vault"
            vault_root.mkdir()
            source = vault_root / "Example_v1.2.3.apk"
            source.write_bytes(b"source")
            config = parse_apps_config(
                {
                    "schemaVersion": 1,
                    "apps": [
                        {
                            "id": "example",
                            "name": "Example",
                            "packageName": "com.example.app",
                            "enabled": True,
                            "mpp": {
                                "owner": "example",
                                "repository": "patches",
                                "path": "example.mpp",
                            },
                            "sourceApk": {
                                "type": "vault",
                                "path": "Example_v1.2.3.apk",
                            },
                        }
                    ],
                }
            )
            planned = create_plan(config, vault_root)[0]
            catalog_app = CatalogApp(
                id="example",
                name="Example",
                package_name="com.example.app",
                version_name="1.2.3",
                version_code=123,
                type="managed",
                release="patched-apks",
                asset="example-1.2.3-patched.apk",
                sha256="a" * 64,
                mpp="example/patches:example.mpp@main",
            )

            unchanged = is_planned_app_unchanged(
                planned,
                catalog_app,
                {"example-1.2.3-patched.apk"},
                "patched-apks",
                "example/patches:example.mpp@main",
            )

        self.assertTrue(unchanged)

    def test_changed_when_mpp_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            vault_root = root / "vault"
            vault_root.mkdir()
            source = vault_root / "Example_v1.2.3.apk"
            source.write_bytes(b"source")
            config = parse_apps_config(
                {
                    "schemaVersion": 1,
                    "apps": [
                        {
                            "id": "example",
                            "name": "Example",
                            "packageName": "com.example.app",
                            "enabled": True,
                            "mpp": {
                                "owner": "example",
                                "repository": "patches",
                                "path": "example.mpp",
                            },
                            "sourceApk": {
                                "type": "vault",
                                "path": "Example_v1.2.3.apk",
                            },
                        }
                    ],
                }
            )
            planned = create_plan(config, vault_root)[0]
            catalog_app = CatalogApp(
                id="example",
                name="Example",
                package_name="com.example.app",
                version_name="1.2.3",
                version_code=123,
                type="managed",
                release="patched-apks",
                asset="example-1.2.3-patched.apk",
                sha256="a" * 64,
                mpp="example/patches:old.mpp@main",
            )

            unchanged = is_planned_app_unchanged(
                planned,
                catalog_app,
                {"example-1.2.3-patched.apk"},
                "patched-apks",
                "example/patches:new.mpp@main",
            )

        self.assertFalse(unchanged)

    def test_sync_publishes_successes_and_reports_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = parse_apps_config(
                {
                    "schemaVersion": 1,
                    "apps": [
                        _app_config("good", "Good"),
                        _app_config("bad", "Bad"),
                    ],
                }
            )
            build_result = BuildResult(
                apps=(
                    BuildAppResult(
                        id="good",
                        name="Good",
                        package_name="com.example.good",
                        source_path=root / "good.apk",
                        patch_input_apk=root / "good-input.apk",
                        patches_path=root / "patches.mpp",
                        unsigned_apk=root / "good-unsigned.apk",
                        output_apk=root / "good.apk",
                        signed=True,
                        converted_source=False,
                    ),
                ),
                failures=(
                    BuildFailureResult(
                        id="bad",
                        name="Bad",
                        package_name="com.example.bad",
                        message="bad: source APK version 1 is not compatible. Update the source APK.",
                    ),
                ),
            )
            publish_result = PublishResult(apps=(), catalog_path=root / "catalog.json")

            with (
                patch("apk_forge.sync.filter_unchanged_apps", return_value=(config, ())),
                patch("apk_forge.sync.run_local_build", return_value=build_result),
                patch("apk_forge.sync.publish_signed_workspace_outputs", return_value=publish_result) as publish,
            ):
                result = sync_build_and_publish(
                    config=config,
                    vault_root=root / "vault",
                    workspace_root=root / "workspace",
                    catalog_path=root / "catalog.json",
                    repository="owner/repo",
                    github_token="token",
                    body_template_path=root / "body.md",
                )

        publish_config = publish.call_args.kwargs["config"]
        self.assertEqual(("good",), tuple(app.id for app in publish_config.enabled_apps))
        self.assertTrue(result.failed)
        summary = format_sync_result(result)
        self.assertIn("Build failed: 1 app(s)", summary)
        self.assertIn("Bad (bad)", summary)


def _app_config(app_id: str, name: str) -> dict:
    return {
        "id": app_id,
        "name": name,
        "packageName": f"com.example.{app_id}",
        "enabled": True,
        "mpp": {
            "owner": "example",
            "repository": "patches",
            "path": f"{app_id}.mpp",
        },
        "sourceApk": {
            "type": "vault",
            "path": f"{app_id}.apk",
        },
    }


if __name__ == "__main__":
    unittest.main()
