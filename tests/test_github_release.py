from __future__ import annotations

import unittest

from apk_forge.github_release import ASSET_LIST_END, ASSET_LIST_START, format_asset_list, inject_asset_list


class GitHubReleaseTest(unittest.TestCase):
    def test_formats_source_package_assets_only(self) -> None:
        self.assertEqual(
            "- `A.apk`\n- `b.apkm`",
            format_asset_list(
                [
                    {"name": "notes.txt"},
                    {"name": "b.apkm"},
                    {"name": "A.apk"},
                ]
            ),
        )

    def test_injects_asset_list_between_markers(self) -> None:
        template = f"before\n{ASSET_LIST_START}\nold\n{ASSET_LIST_END}\nafter"

        self.assertEqual(
            f"before\n{ASSET_LIST_START}\n- `app.apk`\n{ASSET_LIST_END}\nafter",
            inject_asset_list(template, [{"name": "app.apk"}]),
        )

    def test_appends_markers_when_missing(self) -> None:
        body = inject_asset_list("hello\n", [{"name": "app.apk"}])

        self.assertIn(ASSET_LIST_START, body)
        self.assertIn("- `app.apk`", body)
        self.assertIn(ASSET_LIST_END, body)


if __name__ == "__main__":
    unittest.main()
