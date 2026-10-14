from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from apk_forge.archive_publish import format_archive_publish_summary, publish_archive_apks


class FakeReleaseClient:
    def __init__(self, asset_names: set[str] | None = None) -> None:
        self.asset_names = set(asset_names or set())
        self.published: list[Path] = []
        self.pruned_keep_names: set[str] | None = None

    def release_asset_names(self, repository: str, tag: str) -> set[str]:
        return set(self.asset_names)

    def publish_asset(self, spec, apk: Path, allowed_extensions=None) -> dict:
        self.published.append(apk)
        self.asset_names.add(apk.name)
        return {"assets": [{"name": name} for name in sorted(self.asset_names)]}

    def prune_assets(self, spec, keep_names: set[str], allowed_extensions=None) -> tuple[str, ...]:
        self.pruned_keep_names = set(keep_names)
        removed = tuple(sorted(self.asset_names - keep_names))
        self.asset_names = set(keep_names)
        return removed


class ArchivePublishTest(unittest.TestCase):
    def test_publishes_archive_apk(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            vault_root, body_template = self._write_vault(root)
            apk = vault_root / "archive" / "example" / "Example_v1.0.0.apk"
            apk.write_bytes(b"archive")
            client = FakeReleaseClient()

            result = publish_archive_apks(
                vault_root=vault_root,
                repository="owner/private-vault",
                github_token="token",
                body_template_path=body_template,
                archive_id="example",
                client=client,
            )

        self.assertEqual([apk.resolve()], client.published)
        self.assertIn("uploaded: example -> Example_v1.0.0.apk", format_archive_publish_summary(result))

    def test_skips_existing_archive_apk(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            vault_root, body_template = self._write_vault(root)
            apk = vault_root / "archive" / "example" / "Example_v1.0.0.apk"
            apk.write_bytes(b"archive")
            client = FakeReleaseClient({"Example_v1.0.0.apk"})

            result = publish_archive_apks(
                vault_root=vault_root,
                repository="owner/private-vault",
                github_token="token",
                body_template_path=body_template,
                archive_id="example",
                client=client,
            )

        self.assertEqual([], client.published)
        self.assertIn("unchanged: example -> Example_v1.0.0.apk", format_archive_publish_summary(result))

    def test_all_remove_missing_prunes_unreferenced_archive_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            vault_root, body_template = self._write_vault(root)
            first = vault_root / "archive" / "example" / "Example_v1.0.0.apk"
            second = vault_root / "archive" / "other" / "Other_v2.0.0.apk"
            first.write_bytes(b"archive")
            second.parent.mkdir(parents=True)
            second.write_bytes(b"archive")
            client = FakeReleaseClient({"Example_v1.0.0.apk", "Other_v2.0.0.apk", "Old.apk"})

            result = publish_archive_apks(
                vault_root=vault_root,
                repository="owner/private-vault",
                github_token="token",
                body_template_path=body_template,
                all_archives=True,
                remove_missing=True,
                client=client,
            )

        self.assertEqual({"Example_v1.0.0.apk", "Other_v2.0.0.apk"}, client.pruned_keep_names)
        self.assertIn("removed unreferenced asset: Old.apk", format_archive_publish_summary(result))

    def _write_vault(self, root: Path) -> tuple[Path, Path]:
        vault_root = root / "vault"
        archive_dir = vault_root / "archive" / "example"
        archive_dir.mkdir(parents=True)
        body_template = vault_root / "archive-release.md"
        body_template.write_text("Archive APKs\n", encoding="utf-8")
        return vault_root, body_template


if __name__ == "__main__":
    unittest.main()
