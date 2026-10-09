from __future__ import annotations

import subprocess
from dataclasses import dataclass

from apk_forge.errors import ForgeError


class ProcessError(ForgeError):
    """Raised when an external command fails."""


@dataclass(frozen=True)
class ProcessResult:
    args: tuple[str, ...]
    return_code: int
    stdout: str
    stderr: str


def run_process(args: list[str]) -> ProcessResult:
    completed = subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
    )
    result = ProcessResult(
        args=tuple(args),
        return_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
    if result.return_code != 0:
        raise ProcessError(
            f"Command failed with exit code {result.return_code}: {' '.join(result.args)}\n"
            f"{result.stderr.strip()}"
        )
    return result
