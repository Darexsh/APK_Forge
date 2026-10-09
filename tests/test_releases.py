from __future__ import annotations

import unittest
from pathlib import Path

from apk_forge.config import parse_apps_config
from apk_forge.releases import (
    managed_asset_name,
    managed_release_tag,
    patched_signed_asset_name,
    patched_unsigned_asset_name,
    source_version_name,
    source_version_code,
)


class ReleasesTest(unittest.TestCase):
    def test_builds_default_release_names(self) -> None:
        app = parse_apps_config(
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
                            "path": "sources/example.apk",
                        },
                    }
                ],
            }
        ).apps[0]

        self.assertEqual("managed-example-app-1.2.3", managed_release_tag(app, "1.2.3"))
        self.assertEqual("example-app-1.2.3-patched.apk", managed_asset_name(app, "1.2.3"))

    def test_extracts_source_version_from_source_package_name(self) -> None:
        self.assertEqual(
            "1.2.3",
            source_version_name(Path("Example_v1.2.3.apkm")),
        )
        self.assertEqual(
            "0.29.1",
            source_version_name(Path("NewPipe_v0.29.1.apk")),
        )
        self.assertEqual(
            "1.2.3",
            source_version_name(Path("Example-1.2.3.xapk")),
        )
        self.assertEqual(123, source_version_code(Path("Example_v1.2.3.apkm")))

    def test_builds_patched_asset_names_from_source_version(self) -> None:
        app = parse_apps_config(
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
                            "path": "sources/example",
                        },
                    }
                ],
            }
        ).apps[0]

        source_path = Path("Example_v1.2.3.apkm")

        self.assertEqual("example-1.2.3-patched-unsigned.apk", patched_unsigned_asset_name(app, source_path))
        self.assertEqual("example-1.2.3-patched.apk", patched_signed_asset_name(app, source_path))


if __name__ == "__main__":
    unittest.main()
