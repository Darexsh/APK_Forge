from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apk_forge.process import ProcessResult
from apk_forge.source_package import SourcePackageError, prepare_source_package


class SourcePackageTest(unittest.TestCase):
    def test_copies_apk_for_patching(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "Example.apk"
            source.write_bytes(b"apk")

            prepared = prepare_source_package(source, root / "work")
            output_bytes = prepared.patch_input_apk.read_bytes()

        self.assertFalse(prepared.converted)
        self.assertEqual(b"apk", output_bytes)

    def test_bundle_requires_apkeditor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "Example.apkm"
            source.write_bytes(b"bundle")

            with self.assertRaisesRegex(SourcePackageError, "APKEditor"):
                prepare_source_package(source, Path(temp_dir) / "work")

    def test_merges_bundle_with_apkeditor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "Example.apkm"
            source.write_bytes(b"bundle")

            def fake_run(args: list[str]) -> ProcessResult:
                output = Path(args[-1])
                output.write_bytes(b"merged")
                return ProcessResult(args=tuple(args), return_code=0, stdout="", stderr="")

            with patch("apk_forge.source_package.run_process", side_effect=fake_run) as run:
                prepared = prepare_source_package(source, root / "work", root / "APKEditor.jar")
                output_bytes = prepared.patch_input_apk.read_bytes()

            self.assertTrue(prepared.converted)
            self.assertEqual(root / "work" / "Example.apk", prepared.patch_input_apk)
            self.assertEqual(b"merged", output_bytes)
            self.assertEqual(1, run.call_count)


if __name__ == "__main__":
    unittest.main()
