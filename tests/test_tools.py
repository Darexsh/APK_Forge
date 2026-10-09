from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apk_forge.tools import (
    ToolDownloadError,
    resolve_apkeditor,
    resolve_morphe_cli,
    select_release_asset,
)


class ToolsTest(unittest.TestCase):
    def test_selects_morphe_cli_release_asset(self) -> None:
        asset = select_release_asset(
            {
                "assets": [
                    {"name": "morphe-cli-1.0.0-dev.jar", "url": "dev"},
                    {"name": "morphe-cli-1.0.0.jar", "url": "stable"},
                ]
            },
            asset_suffix=".jar",
            name_contains=("morphe",),
            name_excludes=("dev",),
        )

        self.assertEqual("morphe-cli-1.0.0.jar", asset["name"])

    def test_prefers_morphe_all_jar(self) -> None:
        asset = select_release_asset(
            {
                "assets": [
                    {"name": "morphe-desktop-1.10.0.jar", "url": "plain"},
                    {"name": "morphe-desktop-1.10.0-all.jar", "url": "all"},
                ]
            },
            asset_suffix=".jar",
            name_contains=("morphe",),
            prefer_contains=("-all",),
        )

        self.assertEqual("morphe-desktop-1.10.0-all.jar", asset["name"])

    def test_selects_apkeditor_release_asset(self) -> None:
        asset = select_release_asset(
            {
                "assets": [
                    {"name": "README.txt", "url": "text"},
                    {"name": "APKEditor-1.4.0.jar", "url": "jar"},
                ]
            },
            asset_suffix=".jar",
            name_startswith="apkeditor",
        )

        self.assertEqual("APKEditor-1.4.0.jar", asset["name"])

    def test_rejects_ambiguous_tool_assets(self) -> None:
        with self.assertRaisesRegex(ToolDownloadError, "Multiple"):
            select_release_asset(
                {
                    "assets": [
                        {"name": "APKEditor-a.jar", "url": "a"},
                        {"name": "APKEditor-b.jar", "url": "b"},
                    ]
                },
                asset_suffix=".jar",
                name_startswith="apkeditor",
            )

    def test_uses_cached_morphe_cli(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cached = Path(temp_dir) / "tools" / "morphe-cli" / "morphe-cli.jar"
            cached.parent.mkdir(parents=True)
            cached.write_bytes(b"jar")

            with patch("apk_forge.tools.github_release") as github_release:
                resolved = resolve_morphe_cli(Path(temp_dir))

        self.assertEqual(cached, resolved)
        self.assertEqual(0, github_release.call_count)

    def test_downloads_apkeditor_when_not_cached(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            release = {
                "assets": [
                    {
                        "name": "APKEditor-1.4.0.jar",
                        "url": "https://api.github.com/assets/1",
                    }
                ]
            }

            def fake_download(_url: str, output_path: Path, _token: str | None = None) -> None:
                output_path.write_bytes(b"jar")

            with (
                patch("apk_forge.tools.github_release", return_value=release),
                patch("apk_forge.tools.download_asset", side_effect=fake_download),
            ):
                resolved = resolve_apkeditor(Path(temp_dir))
                output_bytes = resolved.read_bytes()

        self.assertEqual("APKEditor-1.4.0.jar", resolved.name)
        self.assertEqual(b"jar", output_bytes)


if __name__ == "__main__":
    unittest.main()
