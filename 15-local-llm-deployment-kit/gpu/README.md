# Real-GPU vLLM benchmark

Measures how one open-weight model (Qwen2.5-7B-Instruct) behaves on a real GPU under vLLM, and which serving
configuration gives the most capacity within an interactive latency SLO.

## Questions it answers

| Experiment | Configs | Question |
|---|---|---|
| Precision | `qwen7b-bf16`, `qwen7b-fp8`, `qwen7b-awq-int4` | How much throughput and how many concurrent users within the SLO does FP8 or 4-bit buy over BF16, and what does it cost per 1M tokens? |
| Prefix caching | `qwen7b-fp8-prefix-cache-on` / `-off` | With a ~2k-token shared system prompt, how much does automatic prefix caching cut time to first token? |

Default SLO (`configs.json`): p95 time to first token ≤ 1 s and median inter-token latency ≤ 50 ms (≥ 20 tokens/s per user).

## What is measured

For each concurrency level (1, 4, 8, 16, 32, 64 streams), from streaming requests with fixed 256-token outputs:

- **TTFT** p50 / p95 / p99 and **inter-token latency** p50 / p95
- **Throughput**: output tokens/s and requests/s across all streams
- **Server state** sampled from vLLM `/metrics`: peak KV-cache usage, peak queued requests, prefix-cache hit rate
- **GPU memory** peak from `nvidia-smi`, and **cost per 1M output tokens** from the GPU's hourly price

`report.py` turns the JSON into `reports/gpu/GPU_BENCHMARK.md` with a summary table, a recommendation,
throughput and TTFT charts, and CV lines generated from the measured numbers.

## Run on Modal (simplest)

```bash
pip install modal
modal setup                                  # one-time browser login
modal run gpu/modal_app.py                   # all 5 configs in parallel, one L4 each
modal run gpu/modal_app.py --only precision  # just the precision comparison
BENCH_GPU=H100 modal run gpu/modal_app.py --only qwen7b-fp8
```

An L4 run of every config takes roughly 15–20 minutes of GPU time per config, so expect a few dollars in total.
Model weights are cached in a Modal volume, so reruns start faster.

## Run on any GPU VM

Needs Docker and the NVIDIA container toolkit (RunPod, Lambda, Vast, Azure NC, AWS g6, GCP g2).

```bash
git clone https://github.com/divyapasupuleti/ai-engineering-projects.git
cd ai-engineering-projects/15-local-llm-deployment-kit
python3 gpu/run_on_vm.py --price 0.80        # USD per GPU-hour for cost per 1M tokens
python3 gpu/report.py
```

## Benchmark any existing endpoint

```bash
python3 gpu/vllm_bench.py --base-url http://HOST:8000/v1 --label my-server --gpu-price-per-hour 2.10
```

Works with vLLM, SGLang, TGI or any OpenAI-compatible server; vLLM-specific metrics are skipped when absent.

## Files

| File | Purpose |
|---|---|
| `vllm_bench.py` | Streaming load generator and metrics sampler |
| `configs.json` | Model, vLLM flags, workload, SLO and GPU prices per experiment |
| `matrix.py` | Start server → wait for `/health` → benchmark → stop |
| `modal_app.py` | Runs the matrix on Modal GPUs |
| `run_on_vm.py` | Runs the matrix with Docker on any GPU machine |
| `report.py` | Builds `GPU_BENCHMARK.md` and charts |

The tests (`tests/test_gpu_bench.py`) run the full path against `tests/fake_vllm.py`, so the harness is checked in CI without a GPU.
