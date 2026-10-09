from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from apk_forge.catalog import Catalog, CatalogApp, load_catalog, write_catalog


class CatalogTest(unittest.TestCase):
    def test_writes_and_loads_catalog(self) -> None:
        catalog = Catalog(
            schema_version=1,
            generated_at="2026-10-08T00:00:00+00:00",
            apps=(
                CatalogApp(
                    id="example-app",
                    name="Example App",
                    package_name="com.example.app",
                    version_name="1.2.3",
                    version_code=123,
                    type="managed",
                    release="managed-example-app-1.2.3",
                    asset="example-app-1.2.3-patched.apk",
                    sha256="a" * 64,
                    mpp="example/patches:patches-1.22.0.mpp@latest",
                ),
            ),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "catalog.json"
            write_catalog(catalog, path)
            loaded = load_catalog(path)

        self.assertEqual(catalog, loaded)

    def test_empty_catalog_has_schema_version_one(self) -> None:
        catalog = Catalog.empty()

        self.assertEqual(1, catalog.schema_version)
        self.assertEqual((), catalog.apps)


if __name__ == "__main__":
    unittest.main()
