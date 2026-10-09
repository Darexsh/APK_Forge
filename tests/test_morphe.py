from __future__ import annotations

import unittest
from pathlib import Path

from apk_forge.morphe import MorpheError, _validate_patch_output, prepare_morphe_patch_command
from apk_forge.process import ProcessResult


class MorpheTest(unittest.TestCase):
    def test_prepares_patch_command(self) -> None:
        command = prepare_morphe_patch_command(
            cli_jar=Path("tools/morphe-cli.jar"),
            patches=Path("patches/example.mpp"),
            input_apk=Path("sources/example.apk"),
            output_apk=Path("outputs/example-patched.apk"),
            include_patches=("Patch A",),
            exclude_patches=("Patch B",),
        )

        self.assertEqual(
            [
                "java",
                "-jar",
                "tools/morphe-cli.jar",
                "patch",
                "--patches",
                "patches/example.mpp",
                "--out",
                "outputs/example-patched.apk",
                "sources/example.apk",
                "-d",
                "Patch B",
                "-e",
                "Patch A",
            ],
            command.as_args(),
        )

    def test_rejects_non_mpp_patches(self) -> None:
        with self.assertRaisesRegex(MorpheError, ".mpp"):
            prepare_morphe_patch_command(
                cli_jar=Path("tools/morphe-cli.jar"),
                patches=Path("patches/example.jar"),
                input_apk=Path("sources/example.apk"),
                output_apk=Path("outputs/example-patched.apk"),
            )

    def test_rejects_zero_patch_output(self) -> None:
        with self.assertRaisesRegex(MorpheError, "0 patches"):
            _validate_patch_output(
                ProcessResult(
                    args=("java", "-jar", "morphe-cli.jar"),
                    return_code=0,
                    stdout="Applying 0 patches",
                    stderr="",
                )
            )


if __name__ == "__main__":
    unittest.main()
