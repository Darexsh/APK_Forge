from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from apk_forge.config import parse_apps_config
from apk_forge.errors import SourceApkError
from apk_forge.output import format_plan
from apk_forge.planner import create_plan
from apk_forge.source_apk import github_release_asset_api_url


class PlannerTest(unittest.TestCase):
    def test_plans_enabled_vault_apks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            vault_root = Path(temp_dir)
            source = vault_root / "sources" / "example.apk"
            source.parent.mkdir()
            source.write_bytes(b"fake apk for planning")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()

            config = parse_apps_config(
                {
                    "schemaVersion": 1,
                    "apps": [
                        _app("enabled-app", "com.example.enabled", "sources/example.apk", digest),
                        {
                            **_app("disabled-app", "com.example.disabled", "missing.apk", None),
                            "enabled": False,
                        },
                    ],
                }
            )

            plan = create_plan(config, vault_root)

            self.assertEqual(1, len(plan))
            self.assertEqual("enabled-app", plan[0].app.id)
            self.assertEqual(digest, plan[0].source_sha256)
            self.assertIn("Example App (enabled-app)", format_plan(plan))
            self.assertIn("Source SHA-256", format_plan(plan))

    def test_rejects_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            vault_root = Path(temp_dir)
            source = vault_root / "example.apk"
            source.write_bytes(b"unexpected")
            config = parse_apps_config(
                {
                    "schemaVersion": 1,
                    "apps": [
                        _app(
                            "example-app",
                            "com.example.app",
                            "example.apk",
                            "0" * 64,
                        )
                    ],
                }
            )

            with self.assertRaisesRegex(SourceApkError, "SHA-256 mismatch"):
                create_plan(config, vault_root)

    def test_accepts_directory_with_exactly_one_source_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            vault_root = Path(temp_dir)
            source_dir = vault_root / "sources" / "example"
            source_dir.mkdir(parents=True)
            source = source_dir / "Example_v1.2.3.apk"
            source.write_bytes(b"fake apk")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            config = parse_apps_config(
                {
                    "schemaVersion": 1,
                    "apps": [_app("example-app", "com.example.app", "sources/example", digest)],
                }
            )

            plan = create_plan(config, vault_root)

        self.assertEqual(source.resolve(), plan[0].source_path)

    def test_accepts_apkm_source_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            vault_root = Path(temp_dir)
            source_dir = vault_root / "sources" / "example"
            source_dir.mkdir(parents=True)
            source = source_dir / "Example_v1.2.3.apkm"
            source.write_bytes(b"fake apkm")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            config = parse_apps_config(
                {
                    "schemaVersion": 1,
                    "apps": [_app("example-app", "com.example.app", "sources/example", digest)],
                }
            )

            plan = create_plan(config, vault_root)

        self.assertEqual(source.resolve(), plan[0].source_path)
        self.assertIn("Patch-ready: needs conversion", format_plan(plan))

    def test_rejects_directory_with_multiple_source_packages(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            vault_root = Path(temp_dir)
            source_dir = vault_root / "sources" / "example"
            source_dir.mkdir(parents=True)
            (source_dir / "one.apk").write_bytes(b"one")
            (source_dir / "two.apk").write_bytes(b"two")
            config = parse_apps_config(
                {
                    "schemaVersion": 1,
                    "apps": [_app("example-app", "com.example.app", "sources/example", None)],
                }
            )

            with self.assertRaisesRegex(SourceApkError, "multiple supported"):
                create_plan(config, vault_root)

    def test_rejects_directory_with_no_source_packages(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            vault_root = Path(temp_dir)
            source_dir = vault_root / "sources" / "example"
            source_dir.mkdir(parents=True)
            (source_dir / "readme.txt").write_text("not an apk", encoding="utf-8")
            config = parse_apps_config(
                {
                    "schemaVersion": 1,
                    "apps": [_app("example-app", "com.example.app", "sources/example", None)],
                }
            )

            with self.assertRaisesRegex(SourceApkError, "contains no supported"):
                create_plan(config, vault_root)

    def test_missing_source_apk_explains_how_to_fix_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = parse_apps_config(
                {
                    "schemaVersion": 1,
                    "apps": [_app("example-app", "com.example.app", "missing.apk", None)],
                }
            )

            with self.assertRaisesRegex(SourceApkError, "Add the source package"):
                create_plan(config, Path(temp_dir))

    def test_github_release_asset_requires_workspace_root(self) -> None:
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
                            "type": "githubReleaseAsset",
                            "repository": "example/private-instance",
                            "release": "source-example-app",
                            "asset": "example-app.apk",
                        },
                    }
                ],
            }
        )

        with self.assertRaisesRegex(SourceApkError, "workspace root"):
            create_plan(config, Path("."))

    def test_github_release_asset_url_encodes_release_and_asset(self) -> None:
        self.assertEqual(
            "https://api.github.com/repos/example/private/releases/tags/source%20app",
            github_release_asset_api_url("example/private", "source app"),
        )

    def test_github_release_asset_url_ignores_asset_for_release_lookup(self) -> None:
        self.assertEqual(
            "https://api.github.com/repos/example/private/releases/tags/source-app",
            github_release_asset_api_url(
                "example/private",
                "source-app",
            ),
        )


def _app(app_id: str, package_name: str, source_path: str, sha256: str | None) -> dict:
    source_apk = {
        "type": "vault",
        "path": source_path,
    }
    if sha256 is not None:
        source_apk["sha256"] = sha256

    return {
        "id": app_id,
        "name": "Example App",
        "packageName": package_name,
        "enabled": True,
        "mpp": {
            "owner": "example",
            "repository": "patches",
            "path": "example.mpp",
        },
        "sourceApk": source_apk,
    }


if __name__ == "__main__":
    unittest.main()
