from __future__ import annotations

import unittest

from apk_forge.models import MppSource
from apk_forge.mpp import mpp_raw_url, mpp_release_url


class MppTest(unittest.TestCase):
    def test_builds_raw_github_url(self) -> None:
        self.assertEqual(
            "https://raw.githubusercontent.com/example/patches/main/example.mpp",
            mpp_raw_url(
                MppSource(
                    owner="example",
                    repository="patches",
                    path="example.mpp",
                    ref="main",
                )
            ),
        )

    def test_preserves_nested_path_and_ref(self) -> None:
        self.assertEqual(
            "https://raw.githubusercontent.com/example/patches/dev/apps/example.mpp",
            mpp_raw_url(
                MppSource(
                    owner="example",
                    repository="patches",
                    path="apps/example.mpp",
                    ref="dev",
                )
            ),
        )

    def test_builds_latest_release_url_when_path_is_omitted(self) -> None:
        self.assertEqual(
            "https://api.github.com/repos/example/patches/releases/latest",
            mpp_release_url(
                MppSource(
                    owner="example",
                    repository="patches",
                )
            ),
        )

    def test_builds_tagged_release_url(self) -> None:
        self.assertEqual(
            "https://api.github.com/repos/example/patches/releases/tags/v1.2.3",
            mpp_release_url(
                MppSource(
                    owner="example",
                    repository="patches",
                    release="v1.2.3",
                )
            ),
        )


if __name__ == "__main__":
    unittest.main()
