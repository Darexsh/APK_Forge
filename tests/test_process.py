from __future__ import annotations

import sys
import unittest

from apk_forge.process import ProcessError, run_process


class ProcessTest(unittest.TestCase):
    def test_returns_success_result(self) -> None:
        result = run_process([sys.executable, "-c", "print('ok')"])

        self.assertEqual(0, result.return_code)
        self.assertEqual("ok", result.stdout.strip())

    def test_raises_on_failure(self) -> None:
        with self.assertRaisesRegex(ProcessError, "exit code 7"):
            run_process([sys.executable, "-c", "import sys; sys.exit(7)"])


if __name__ == "__main__":
    unittest.main()
