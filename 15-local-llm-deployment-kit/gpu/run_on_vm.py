#!/usr/bin/env python3
"""Run the benchmark matrix on any Linux GPU machine with Docker and the NVIDIA container toolkit
(RunPod, Lambda, Vast, Azure NC/ND, AWS g6/p4, GCP g2).

    git clone https://github.com/divyapasupuleti/ai-engineering-projects.git
    cd ai-engineering-projects/15-local-llm-deployment-kit
    python3 gpu/run_on_vm.py --price 0.80                # every config
    python3 gpu/run_on_vm.py --only precision            # one group
    python3 gpu/report.py                                # build reports/gpu/GPU_BENCHMARK.md
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import matrix  # noqa: E402

REPORTS = HERE.parent / "reports" / "gpu"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", default="", help="comma-separated labels or groups")
    ap.add_argument("--price", type=float, help="USD per GPU-hour for cost per 1M tokens")
    ap.add_argument("--native", action="store_true", help="run `python3 -m vllm...` directly instead of Docker")
    ap.add_argument("--hf-cache", default=os.path.expanduser("~/.cache/huggingface"))
    args = ap.parse_args()

    cfg = matrix.load()
    failures = []
    for config in matrix.select(cfg, args.only):
        name = f"vllm-bench-{config['label']}"
        if args.native:
            cmd, stop = matrix.native_command(config, cfg["server"]), None
        else:
            cmd = matrix.docker_command(config, cfg["server"], name, args.hf_cache, os.environ.get("HF_TOKEN"))
            stop = lambda n=name: subprocess.run(["docker", "rm", "-f", n], capture_output=True)  # noqa: E731
        print(f"\n=== {config['label']}: {config['description']}")
        try:
            matrix.run_one(config, cfg, cmd, REPORTS / f"{config['label']}.json", args.price, REPORTS / "logs", stop)
        except RuntimeError as e:
            print(f"  FAILED: {e}")
            failures.append(config["label"])
    print(f"\nDone. Failed: {', '.join(failures) or 'none'}. Next: python3 gpu/report.py")


if __name__ == "__main__":
    main()
