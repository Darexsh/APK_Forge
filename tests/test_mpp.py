from __future__ import annotations

import unittest

from apk_forge.models import MppSource
from apk_forge.mpp import mpp_raw_url, mpp_release_url, parse_compatible_versions, resolve_mpp_identifier


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

    def test_resolves_path_mpp_identifier(self) -> None:
        self.assertEqual(
            "example/patches:example.mpp@dev",
            resolve_mpp_identifier(
                MppSource(
                    owner="example",
                    repository="patches",
                    path="apps/example.mpp",
                    ref="dev",
                )
            ),
        )

    def test_parses_compatible_versions(self) -> None:
        output = """INFO: Package name: com.example.app
Most common compatible versions:
\t1.2.3 [versionCodes: ARM64_V8A=123] (1 patch)
\t1.2.4 (2 patches)
"""

        self.assertEqual(("1.2.3", "1.2.4"), parse_compatible_versions(output))

    def test_parses_any_compatible_version(self) -> None:
        output = """INFO: Package name: com.example.app
Most common compatible versions:
\tany (1 patch)
"""

        self.assertEqual(("any",), parse_compatible_versions(output))


if __name__ == "__main__":
    unittest.main()
