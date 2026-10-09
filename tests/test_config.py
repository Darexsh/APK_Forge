from __future__ import annotations

import unittest

from apk_forge.config import parse_apps_config
from apk_forge.errors import ConfigError


class ConfigTest(unittest.TestCase):
    def test_parses_valid_config(self) -> None:
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
                            "path": "sources/example.apk",
                        },
                    }
                ],
            }
        )

        self.assertEqual(1, len(config.apps))
        self.assertEqual(1, len(config.enabled_apps))
        self.assertEqual("managed-example-app", config.apps[0].output.release_prefix)
        self.assertEqual("main", config.apps[0].mpp.ref)

    def test_rejects_duplicate_ids(self) -> None:
        app = {
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

        with self.assertRaisesRegex(ConfigError, "Duplicate app id"):
            parse_apps_config({"schemaVersion": 1, "apps": [app, {**app, "packageName": "other"}]})

    def test_rejects_public_download_sources(self) -> None:
        with self.assertRaisesRegex(ConfigError, "type must be 'vault'"):
            parse_apps_config(
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
                                "type": "apkmirror",
                                "path": "ignored",
                            },
                        }
                    ],
                }
            )

    def test_parses_github_release_asset_source(self) -> None:
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

        source = config.apps[0].source_apk
        self.assertEqual("githubReleaseAsset", source.type)
        self.assertEqual("example/private-instance", source.repository)
        self.assertEqual("source-example-app", source.release)
        self.assertEqual("example-app.apk", source.asset)

    def test_parses_mpp_release_source_without_path(self) -> None:
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
                            "release": "latest",
                        },
                        "sourceApk": {
                            "type": "vault",
                            "path": "sources/example.apk",
                        },
                    }
                ],
            }
        )

        self.assertIsNone(config.apps[0].mpp.path)
        self.assertEqual("latest", config.apps[0].mpp.release)


if __name__ == "__main__":
    unittest.main()
