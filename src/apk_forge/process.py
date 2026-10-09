from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Callable

from apk_forge.errors import ForgeError


class ProcessError(ForgeError):
    """Raised when an external command fails."""


@dataclass(frozen=True)
class ProcessResult:
    args: tuple[str, ...]
    return_code: int
    stdout: str
    stderr: str


def run_process(args: list[str], output: Callable[[str], None] | None = None) -> ProcessResult:
    if output is not None:
        return _run_process_streaming(args, output)

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


def _run_process_streaming(args: list[str], output: Callable[[str], None]) -> ProcessResult:
    process = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    lines: list[str] = []
    assert process.stdout is not None
    with process.stdout:
        for line in process.stdout:
            lines.append(line)
            output(line.rstrip("\n"))
    return_code = process.wait()
    stdout = "".join(lines)
    result = ProcessResult(
        args=tuple(args),
        return_code=return_code,
        stdout=stdout,
        stderr="",
    )
    if result.return_code != 0:
        raise ProcessError(
            f"Command failed with exit code {result.return_code}: {' '.join(result.args)}\n"
            f"{result.stdout.strip()}"
        )
    return result
