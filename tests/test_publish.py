from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from apk_forge.catalog import load_catalog
from apk_forge.config import parse_apps_config
from apk_forge.publish import format_publish_result, publish_signed_workspace_outputs


class FakeReleaseClient:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, Path]] = []

    def publish_asset(self, spec, apk: Path) -> dict:
        self.published.append((spec.repository, spec.tag, apk))
        return {"assets": [{"name": apk.name}]}


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
            )
            catalog = load_catalog(catalog_path)

        self.assertEqual(1, len(client.published))
        self.assertEqual("patched-apks", client.published[0][1])
        self.assertEqual("example-1.2.3-patched.apk", catalog.apps[0].asset)
        self.assertEqual("1.2.3", catalog.apps[0].version_name)
        self.assertEqual(123, catalog.apps[0].version_code)
        self.assertIn("Published: 1 app(s)", format_publish_result(result))


if __name__ == "__main__":
    unittest.main()
