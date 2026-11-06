#!/usr/bin/env python3
"""Run every project's unit tests in its own subprocess (module names repeat across projects).

    python run_all_tests.py
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent


def main() -> int:
    failed = []
    total = 0
    for project in sorted(p for p in REPO.glob("[0-9][0-9]-*") if (p / "tests").is_dir()):
        start = time.perf_counter()
        proc = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"],
                              cwd=project, capture_output=True, text=True, timeout=600)
        m = re.search(r"Ran (\d+) tests?", proc.stderr)
        n = int(m.group(1)) if m else 0
        total += n
        ok = proc.returncode == 0
        print(f"{'PASS' if ok else 'FAIL'}  {project.name:<34} {n:>3} tests  {time.perf_counter() - start:5.1f}s")
        if not ok:
            failed.append(project.name)
            print(proc.stderr[-2000:])
    print(f"\n{total} tests across {len(list(REPO.glob('[0-9][0-9]-*')))} projects; "
          f"{'all passed' if not failed else 'FAILED: ' + ', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
