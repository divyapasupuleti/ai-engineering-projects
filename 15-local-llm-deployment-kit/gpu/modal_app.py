"""Run the vLLM benchmark matrix on Modal cloud GPUs, one GPU per config in parallel.

    pip install modal && modal setup                     # one-time browser login
    modal run gpu/modal_app.py                           # every config on an L4
    modal run gpu/modal_app.py --only precision          # one group
    BENCH_GPU=H100 modal run gpu/modal_app.py --only qwen7b-fp8

Results land in reports/gpu/<label>.json and reports/gpu/GPU_BENCHMARK.md.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import modal

HERE = Path(__file__).resolve().parent
GPU = os.environ.get("BENCH_GPU", "L4")
VLLM_VERSION = os.environ.get("VLLM_VERSION", "")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(f"vllm=={VLLM_VERSION}" if VLLM_VERSION else "vllm", "huggingface_hub[hf_transfer]")
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "1"})
    .add_local_dir(HERE, "/bench")
)
hf_cache = modal.Volume.from_name("vllm-bench-hf-cache", create_if_missing=True)
app = modal.App("vllm-inference-bench")


@app.function(image=image, gpu=GPU, timeout=2 * 60 * 60, volumes={"/root/.cache/huggingface": hf_cache})
def run_config(config: dict, cfg: dict, price: float | None) -> dict:
    sys.path.insert(0, "/bench")
    import matrix

    out = Path("/tmp/results") / f"{config['label']}.json"
    try:
        result = matrix.run_one(config, cfg, matrix.native_command(config, cfg["server"]), out, price, Path("/tmp/logs"))
    except RuntimeError as e:
        return {"label": config["label"], "error": str(e)}
    finally:
        hf_cache.commit()
    result["gpu_type_requested"] = GPU
    return result


@app.local_entrypoint()
def main(only: str = "", price: float = 0.0):
    sys.path.insert(0, str(HERE))
    import matrix
    import report

    cfg = matrix.load()
    configs = matrix.select(cfg, only)
    price = price or cfg["gpu_prices_usd_per_hour"].get(GPU)
    print(f"Running {len(configs)} config(s) on {GPU} at ~${price}/GPU-hour: {', '.join(c['label'] for c in configs)}")
    out_dir = HERE.parent / "reports" / "gpu"
    out_dir.mkdir(parents=True, exist_ok=True)
    for result in run_config.starmap([(c, cfg, price) for c in configs]):
        if "error" in result:
            print(f"FAILED {result['label']}: {result['error'][-1500:]}")
            continue
        (out_dir / f"{result['label']}.json").write_text(json.dumps(result, indent=2))
        print(f"saved {result['label']}")
    print(report.build(out_dir))
