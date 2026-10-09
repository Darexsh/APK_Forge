from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from apk_forge.catalog import load_catalog
from apk_forge.catalog import Catalog, CatalogApp
from apk_forge.config import parse_apps_config
from apk_forge.publish import (
    format_patched_release_asset_list,
    format_publish_result,
    publish_signed_workspace_outputs,
)


class FakeReleaseClient:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, Path]] = []
        self.synced_lists: list[str | None] = []

    def publish_asset(self, spec, apk: Path) -> dict:
        self.published.append((spec.repository, spec.tag, apk))
        return {"assets": [{"name": apk.name}]}

    def ensure_release(self, spec) -> dict:
        self.synced_lists.append(spec.asset_list)
        return {"assets": []}


class PublishTest(unittest.TestCase):
    def test_publishes_signed_apk_and_updates_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            vault_root = root / "vault"
            workspace_root = root / "workspace"
            vault_root.mkdir()
            catalog_path = vault_root / "catalog.json"
            body_template = vault_root / "patched-release.md"
            body_template.write_text("patched apks\n", encoding="utf-8")
            source = vault_root / "Example_v1.2.3.apk"
            source.write_bytes(b"source")
            apk = workspace_root / "build" / "example" / "signed" / "example-1.2.3-patched.apk"
            apk.parent.mkdir(parents=True)
            apk.write_bytes(b"signed")
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
                            "patches": {
                                "enable": ["Patch A"],
                                "disable": ["Patch B"],
                            },
                            "sourceApk": {
                                "type": "vault",
                                "path": "Example_v1.2.3.apk",
                            },
                        }
                    ],
                }
            )
            client = FakeReleaseClient()

            result = publish_signed_workspace_outputs(
                config=config,
                vault_root=vault_root,
                workspace_root=workspace_root,
                catalog_path=catalog_path,
                repository="example/private-instance",
                github_token="token",
                body_template_path=body_template,
                client=client,
                mpp_paths={"example": workspace_root / "build" / "example" / "patches" / "patches-1.22.0.mpp"},
            )
            catalog = load_catalog(catalog_path)

        self.assertEqual(1, len(client.published))
        self.assertEqual("patched-apks", client.published[0][1])
        self.assertEqual("example-1.2.3-patched.apk", catalog.apps[0].asset)
        self.assertEqual("1.2.3", catalog.apps[0].version_name)
        self.assertEqual(123, catalog.apps[0].version_code)
        self.assertEqual("example/patches:example.mpp@main", catalog.apps[0].mpp)
        self.assertEqual(("Patch A",), catalog.apps[0].patches_enable)
        self.assertEqual(("Patch B",), catalog.apps[0].patches_disable)
        self.assertIn("MPP: `example/patches:example.mpp@main`", client.synced_lists[-1] or "")
        self.assertIn("Published: 1 app(s)", format_publish_result(result))

    def test_formats_patched_release_asset_list_with_mpp_source(self) -> None:
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
                            "release": "latest",
                        },
                        "sourceApk": {
                            "type": "vault",
                            "path": "Example_v1.2.3.apk",
                        },
                    }
                ],
            }
        )
        catalog = Catalog(
            schema_version=1,
            generated_at="2026-10-09T00:00:00+00:00",
            apps=(
                CatalogApp(
                    id="example",
                    name="Example",
                    package_name="com.example.app",
                    version_name="1.2.3",
                    version_code=123,
                    type="managed",
                    release="patched-apks",
                    asset="example-1.2.3-patched.apk",
                    sha256="abc",
                    mpp="example/patches:patches-1.22.0.mpp@latest",
                ),
            ),
        )

        release_list = format_patched_release_asset_list(catalog, config)

        self.assertIn("- `example-1.2.3-patched.apk`", release_list)
        self.assertIn("App: Example (`com.example.app`)", release_list)
        self.assertIn("Version: 1.2.3 (123)", release_list)
        self.assertIn("MPP: `example/patches:patches-1.22.0.mpp@latest`", release_list)


if __name__ == "__main__":
    unittest.main()
