from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from apk_forge.signing import (
    SigningError,
    prepare_sign_command,
    prepare_verify_command,
    resolve_apksigner,
    resolve_default_keystore,
)


class SigningTest(unittest.TestCase):
    def test_prepares_sign_command(self) -> None:
        command = prepare_sign_command(
            apksigner=Path("build-tools/apksigner"),
            keystore=Path("private/signing.jks"),
            key_alias="release",
            input_apk=Path("outputs/unsigned.apk"),
            output_apk=Path("outputs/signed.apk"),
        )

        self.assertEqual(
            [
                "build-tools/apksigner",
                "sign",
                "--verbose",
                "--ks",
                "private/signing.jks",
                "--ks-key-alias",
                "release",
                "--in",
                "outputs/unsigned.apk",
                "--out",
                "outputs/signed.apk",
            ],
            command.as_args(),
        )

    def test_prepares_sign_command_with_passwords(self) -> None:
        command = prepare_sign_command(
            apksigner=Path("build-tools/apksigner"),
            keystore=Path("private/signing.jks"),
            key_alias="public",
            input_apk=Path("outputs/unsigned.apk"),
            output_apk=Path("outputs/signed.apk"),
            keystore_password="public",
            key_password="public",
        )

        self.assertIn("--ks-pass", command.as_args())
        self.assertIn("pass:public", command.as_args())
        self.assertIn("--key-pass", command.as_args())

    def test_prepares_verify_command(self) -> None:
        command = prepare_verify_command(
            apksigner=Path("build-tools/apksigner"),
            apk=Path("outputs/signed.apk"),
        )

        self.assertEqual(
            ["build-tools/apksigner", "verify", "--verbose", "outputs/signed.apk"],
            command.as_args(),
        )

    def test_rejects_empty_alias(self) -> None:
        with self.assertRaisesRegex(SigningError, "alias"):
            prepare_sign_command(
                apksigner=Path("apksigner"),
                keystore=Path("signing.jks"),
                key_alias="",
                input_apk=Path("input.apk"),
                output_apk=Path("output.apk"),
            )

    def test_resolves_default_keystore_from_vault(self) -> None:
        keystore = resolve_default_keystore(Path("private"), Path(__file__))

        self.assertEqual(Path(__file__), keystore)

    def test_resolves_apksigner_from_path(self) -> None:
        with patch("apk_forge.signing.shutil.which", return_value="/sdk/apksigner"):
            self.assertEqual(Path("/sdk/apksigner"), resolve_apksigner())

    def test_resolves_windows_local_appdata_sdk(self) -> None:
        with (
            patch("apk_forge.signing.shutil.which", return_value=None),
            patch("apk_forge.signing.os.environ.get", side_effect=lambda key: "C:/Users/me/AppData/Local" if key == "LOCALAPPDATA" else None),
            patch("pathlib.Path.is_dir", new=lambda path: str(path).endswith("build-tools")),
            patch("pathlib.Path.iterdir", return_value=[Path("35.0.0")]),
            patch("pathlib.Path.is_file", return_value=True),
            patch("apk_forge.signing._apksigner_binary_name", return_value="apksigner.bat"),
        ):
            resolved = resolve_apksigner()

        self.assertEqual(Path("35.0.0") / "apksigner.bat", resolved)


if __name__ == "__main__":
    unittest.main()
