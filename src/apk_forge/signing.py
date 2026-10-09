from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from apk_forge.errors import ForgeError
from apk_forge.process import ProcessResult, run_process


class SigningError(ForgeError):
    """Raised when an APK signing command cannot be prepared."""


@dataclass(frozen=True)
class SignCommand:
    apksigner: Path
    keystore: Path
    key_alias: str
    input_apk: Path
    output_apk: Path
    keystore_password: str | None = None
    key_password: str | None = None
    min_sdk_version: int | None = None

    def as_args(self) -> list[str]:
        args = [
            str(self.apksigner),
            "sign",
            "--verbose",
            "--ks",
            str(self.keystore),
        ]
        if self.keystore_password is not None:
            args.extend(["--ks-pass", f"pass:{self.keystore_password}"])
        if self.key_password is not None:
            args.extend(["--key-pass", f"pass:{self.key_password}"])
        if self.min_sdk_version is not None:
            args.extend(["--min-sdk-version", str(self.min_sdk_version)])
        args.extend(
            [
                "--ks-key-alias",
                self.key_alias,
                "--in",
                str(self.input_apk),
                "--out",
                str(self.output_apk),
            ]
        )
        return args


@dataclass(frozen=True)
class VerifyCommand:
    apksigner: Path
    apk: Path

    def as_args(self) -> list[str]:
        return [
            str(self.apksigner),
            "verify",
            "--verbose",
            str(self.apk),
        ]


def prepare_sign_command(
    apksigner: Path,
    keystore: Path,
    key_alias: str,
    input_apk: Path,
    output_apk: Path,
    keystore_password: str | None = None,
    key_password: str | None = None,
    min_sdk_version: int | None = None,
) -> SignCommand:
    if not key_alias.strip():
        raise SigningError("Signing key alias must not be empty")
    _require_apk(input_apk, "Input")
    _require_apk(output_apk, "Output")

    return SignCommand(
        apksigner=apksigner,
        keystore=keystore,
        key_alias=key_alias,
        input_apk=input_apk,
        output_apk=output_apk,
        keystore_password=keystore_password,
        key_password=key_password,
        min_sdk_version=min_sdk_version,
    )


def prepare_verify_command(apksigner: Path, apk: Path) -> VerifyCommand:
    _require_apk(apk, "Verify")
    return VerifyCommand(apksigner=apksigner, apk=apk)


def sign_apk(command: SignCommand) -> ProcessResult:
    try:
        result = run_process(command.as_args())
    except ForgeError:
        if command.min_sdk_version is not None:
            raise
        result = run_process(
            SignCommand(
                apksigner=command.apksigner,
                keystore=command.keystore,
                key_alias=command.key_alias,
                input_apk=command.input_apk,
                output_apk=command.output_apk,
                keystore_password=command.keystore_password,
                key_password=command.key_password,
                min_sdk_version=21,
            ).as_args()
        )
    if not command.output_apk.is_file():
        raise SigningError(f"apksigner did not create signed APK: {command.output_apk}")
    return result


def verify_apk(command: VerifyCommand) -> ProcessResult:
    return run_process(command.as_args())


def _require_apk(path: Path, label: str) -> None:
    if path.suffix.lower() != ".apk":
        raise SigningError(f"{label} file must be an APK: {path}")


def resolve_default_keystore(vault_root: Path, configured_path: Path | None = None) -> Path:
    keystore = configured_path if configured_path is not None else vault_root / "keystore" / "public.jks"
    if not keystore.is_file():
        raise SigningError(f"Signing keystore does not exist: {keystore}")
    return keystore


def resolve_apksigner(configured_path: Path | None = None) -> Path:
    if configured_path is not None:
        if not configured_path.is_file():
            raise SigningError(f"apksigner does not exist: {configured_path}")
        return configured_path

    on_path = shutil.which("apksigner")
    if on_path:
        return Path(on_path)

    sdk_roots = [
        Path("/usr/local/lib/android/sdk"),
        _optional_path(os.environ.get("ANDROID_HOME")),
        _optional_path(os.environ.get("ANDROID_SDK_ROOT")),
        _windows_local_appdata_sdk(),
    ]
    for root in sdk_roots:
        if root is None:
            continue
        build_tools_dir = root / "build-tools"
        if not build_tools_dir.is_dir():
            continue
        for version_dir in sorted(build_tools_dir.iterdir(), reverse=True):
            candidate = version_dir / _apksigner_binary_name()
            if candidate.is_file():
                return candidate

    raise SigningError(
        "apksigner not found. Put it on PATH, set ANDROID_HOME/ANDROID_SDK_ROOT, or pass --apksigner."
    )


def _optional_path(value: str | None) -> Path | None:
    return Path(value) if value else None


def _windows_local_appdata_sdk() -> Path | None:
    local_appdata = os.environ.get("LOCALAPPDATA")
    if not local_appdata:
        return None
    return Path(local_appdata) / "Android" / "Sdk"


def _apksigner_binary_name() -> str:
    return "apksigner.bat" if os.name == "nt" else "apksigner"
