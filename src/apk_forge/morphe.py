from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from apk_forge.errors import ForgeError
from apk_forge.process import ProcessResult, run_process


class MorpheError(ForgeError):
    """Raised when a Morphe patch command cannot be prepared."""


@dataclass(frozen=True)
class MorphePatchCommand:
    cli_jar: Path
    patches: Path
    input_apk: Path
    output_apk: Path
    include_patches: tuple[str, ...] = ()
    exclude_patches: tuple[str, ...] = ()

    def as_args(self) -> list[str]:
        args = [
            "java",
            "-jar",
            str(self.cli_jar),
            "patch",
            "--patches",
            str(self.patches),
            "--out",
            str(self.output_apk),
            str(self.input_apk),
        ]

        for patch in self.exclude_patches:
            args.extend(["-d", patch])
        for patch in self.include_patches:
            args.extend(["-e", patch])

        return args


def prepare_morphe_patch_command(
    cli_jar: Path,
    patches: Path,
    input_apk: Path,
    output_apk: Path,
    include_patches: tuple[str, ...] = (),
    exclude_patches: tuple[str, ...] = (),
) -> MorphePatchCommand:
    if cli_jar.suffix.lower() != ".jar":
        raise MorpheError(f"Morphe CLI must be a .jar file: {cli_jar}")
    if patches.suffix.lower() != ".mpp":
        raise MorpheError(f"Morphe patches must be a .mpp file: {patches}")
    if input_apk.suffix.lower() != ".apk":
        raise MorpheError(f"Input file must be an APK: {input_apk}")
    if output_apk.suffix.lower() != ".apk":
        raise MorpheError(f"Output file must be an APK: {output_apk}")

    return MorphePatchCommand(
        cli_jar=cli_jar,
        patches=patches,
        input_apk=input_apk,
        output_apk=output_apk,
        include_patches=include_patches,
        exclude_patches=exclude_patches,
    )


def patch_apk(command: MorphePatchCommand) -> ProcessResult:
    result = run_process(command.as_args())
    _validate_patch_output(result)
    if not command.output_apk.is_file():
        raise MorpheError(f"Morphe did not create output APK: {command.output_apk}")
    return result


def _validate_patch_output(result: ProcessResult) -> None:
    combined_output = f"{result.stdout}\n{result.stderr}".lower()
    if "applying 0 patches" in combined_output:
        raise MorpheError("Morphe applied 0 patches; refusing to accept an unpatched APK")
