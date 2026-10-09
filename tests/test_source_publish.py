from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from apk_forge.source_apk import sha256_file
from apk_forge.source_publish import (
    format_source_publish_summary,
    publish_source_packages,
)


class FakeReleaseClient:
    def __init__(self, asset_names: set[str] | None = None) -> None:
        self.asset_names = set(asset_names or set())
        self.published: list[Path] = []
        self.removed: list[str] = []
        self.pruned_keep_names: set[str] | None = None

    def release_asset_names(self, repository: str, tag: str) -> set[str]:
        return set(self.asset_names)

    def publish_asset(self, spec, apk: Path, allowed_extensions=None) -> dict:
        self.published.append(apk)
        self.asset_names.add(apk.name)
        return {"assets": [{"name": name} for name in sorted(self.asset_names)]}

    def remove_asset_by_name(self, spec, asset_name: str) -> bool:
        self.removed.append(asset_name)
        self.asset_names.discard(asset_name)
        return True

    def prune_assets(self, spec, keep_names: set[str], allowed_extensions=None) -> tuple[str, ...]:
        self.pruned_keep_names = set(keep_names)
        removed = tuple(sorted(self.asset_names - keep_names))
        self.asset_names = set(keep_names)
        return removed


class SourcePublishTest(unittest.TestCase):
    def test_publishes_source_package_and_updates_apps_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path, vault_root, body_template = self._write_vault(root)
            package = vault_root / "sources" / "example" / "Example_v1.2.3.apkm"
            package.write_bytes(b"source")
            client = FakeReleaseClient()

            result = publish_source_packages(
                config_path=config_path,
                vault_root=vault_root,
                repository="owner/private-vault",
                github_token="token",
                body_template_path=body_template,
                app_id="example",
                client=client,
            )
            config = json.loads(config_path.read_text(encoding="utf-8"))
            digest = sha256_file(package)

        self.assertEqual([package.resolve()], client.published)
        self.assertEqual("Example_v1.2.3.apkm", config["apps"][0]["sourceApk"]["asset"])
        self.assertEqual(digest, config["apps"][0]["sourceApk"]["sha256"])
        self.assertIn("updated: example", format_source_publish_summary(result))

    def test_skip_upload_only_configures_local_apps_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path, vault_root, body_template = self._write_vault(root)
            (vault_root / "sources" / "example" / "Example_v1.2.3.apk").write_bytes(b"source")
            client = FakeReleaseClient()

            result = publish_source_packages(
                config_path=config_path,
                vault_root=vault_root,
                repository="owner/private-vault",
                github_token="",
                body_template_path=body_template,
                app_id="example",
                skip_upload=True,
                client=client,
            )
            config = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual([], client.published)
        self.assertEqual("githubReleaseAsset", config["apps"][0]["sourceApk"]["type"])
        self.assertIn("configured: example", format_source_publish_summary(result))

    def test_all_remove_missing_removes_configured_app_and_asset(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path, vault_root, body_template = self._write_vault(root)
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["apps"][0]["sourceApk"] = {
                "type": "githubReleaseAsset",
                "repository": "owner/private-vault",
                "release": "source-apks",
                "asset": "Example_v1.2.3.apk",
                "sha256": "abc",
            }
            config_path.write_text(json.dumps(config), encoding="utf-8")
            source_dir = vault_root / "sources" / "example"
            for child in source_dir.iterdir():
                child.unlink()
            source_dir.rmdir()
            client = FakeReleaseClient({"Example_v1.2.3.apk", "old.apk"})

            result = publish_source_packages(
                config_path=config_path,
                vault_root=vault_root,
                repository="owner/private-vault",
                github_token="token",
                body_template_path=body_template,
                all_apps=True,
                remove_missing=True,
                client=client,
            )
            updated = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual([], updated["apps"])
        self.assertIn("Example_v1.2.3.apk", client.removed)
        self.assertEqual(set(), client.pruned_keep_names)
        self.assertIn("removed missing: example", format_source_publish_summary(result))

    def _write_vault(self, root: Path) -> tuple[Path, Path, Path]:
        vault_root = root / "vault"
        source_dir = vault_root / "sources" / "example"
        source_dir.mkdir(parents=True)
        body_template = vault_root / "source-release.md"
        body_template.write_text("Source APKs\n", encoding="utf-8")
        config_path = vault_root / "apps.json"
        config_path.write_text(
            json.dumps(
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
                                "release": "latest",
                            },
                            "sourceApk": {
                                "type": "vault",
                                "path": "sources/example/",
                            },
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return config_path, vault_root, body_template


if __name__ == "__main__":
    unittest.main()
