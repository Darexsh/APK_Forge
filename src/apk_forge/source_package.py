from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from apk_forge.errors import ForgeError
from apk_forge.process import run_process

BUNDLE_SUFFIXES = {".apkm", ".apks", ".xapk"}


class SourcePackageError(ForgeError):
    """Raised when a source package cannot be prepared for patching."""


@dataclass(frozen=True)
class PreparedSourcePackage:
    source_path: Path
    patch_input_apk: Path
    converted: bool


def prepare_source_package(
    source_path: Path,
    output_dir: Path,
    apkeditor_jar: Path | None = None,
) -> PreparedSourcePackage:
    output_dir.mkdir(parents=True, exist_ok=True)

    suffix = source_path.suffix.lower()
    if suffix == ".apk":
        patch_input = output_dir / source_path.name
        if source_path.resolve() != patch_input.resolve():
            shutil.copy2(source_path, patch_input)
        return PreparedSourcePackage(
            source_path=source_path,
            patch_input_apk=patch_input,
            converted=False,
        )

    if suffix not in BUNDLE_SUFFIXES:
        raise SourcePackageError(f"Unsupported source package for patching: {source_path}")

    if apkeditor_jar is None:
        raise SourcePackageError(
            f"Bundle source requires APKEditor via --apkeditor-jar before patching: {source_path.name}"
        )
    if apkeditor_jar.suffix.lower() != ".jar":
        raise SourcePackageError(f"APKEditor must be a .jar file: {apkeditor_jar}")

    patch_input = output_dir / f"{source_path.stem}.apk"
    run_process(
        [
            "java",
            "-jar",
            str(apkeditor_jar),
            "m",
            "-f",
            "-i",
            str(source_path),
            "-o",
            str(patch_input),
        ]
    )
    if not patch_input.is_file():
        raise SourcePackageError(f"APKEditor did not create merged APK: {patch_input}")

    return PreparedSourcePackage(
        source_path=source_path,
        patch_input_apk=patch_input,
        converted=True,
    )
