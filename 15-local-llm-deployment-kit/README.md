# Project 15: Local LLM Deployment Kit

`Deployment` `Self-hosting` `Quantization` `Observability` `Data residency`

An OpenAI-compatible gateway for local models with quantization benchmarking, back-pressure, Prometheus metrics, health-checked model switching and one-command rollback.

## Goals
| Goal | Success criterion |
|---|---|
| OpenAI-compatible API | /v1/chat/completions (incl. SSE streaming), /v1/models, API keys |
| Quantization benchmark | p50/p95, TTFT, tokens/s, 429s at 1/4/8/16 concurrency per profile |
| Fit to hardware + SLO | Memory budget and p95 SLO pick the highest-quality profile |
| Safe operations | Health-checked switch, memory guard, rollback, back-pressure (429) |
| Observable | Prometheus counters, latency histogram, inflight gauge; docker-compose with Ollama + Prometheus |

## Architecture
![Architecture](docs/ARCHITECTURE.png)

<details><summary>Mermaid source</summary>

```mermaid
flowchart LR
    apps["Existing apps<br/>OpenAI SDK,<br/>base_url = local"]:::client
    gateway["OpenAI-compatible<br/>gateway<br/>/v1/chat/completions"]:::api
    auth["API-key auth"]:::logic
    limiter["Back-pressure<br/>parallel slots +<br/>queue -> 429"]:::logic
    manager["Model manager<br/>profiles, memory guard,<br/>health check, rollback"]:::logic
    ollama["Ollama backend<br/>llama3.1 / qwen2.5<br/>q4 / q8 / fp16"]:::llm
    sim["Simulated backend<br/>TTFT, tok/s, slots<br/>from profile"]:::llm
    metrics["/metrics<br/>counters, histogram,<br/>inflight"]:::eval
    bench["Benchmark<br/>concurrency sweep<br/>-> recommendation"]:::eval
    prom["Prometheus /<br/>Grafana"]:::ui
    apps -->|HTTP| gateway
    gateway --> auth
    gateway --> limiter
    auth --> manager
    limiter --> manager
    manager -->|if running| ollama
    manager -->|fallback| sim
    ollama --> metrics
    sim --> bench
    metrics -->|scrape| prom
    bench -->|choose profile| manager
    classDef client fill:#E3F2FD,stroke:#1565C0,color:#1A1A1A
    classDef api fill:#E8F5E9,stroke:#2E7D32,color:#1A1A1A
    classDef logic fill:#FFF3E0,stroke:#E65100,color:#1A1A1A
    classDef store fill:#F3E5F5,stroke:#6A1B9A,color:#1A1A1A
    classDef llm fill:#FCE4EC,stroke:#AD1457,color:#1A1A1A
    classDef eval fill:#E0F7FA,stroke:#00838F,color:#1A1A1A
    classDef ui fill:#FFFDE7,stroke:#F9A825,color:#1A1A1A
    classDef external fill:#ECEFF1,stroke:#455A64,color:#1A1A1A
```
</details>

## Quick start
No third-party packages needed (Python 3.10+).

```bash
python benchmark.py                       # simulator
python llm_server.py --simulate --port 8815
python benchmark.py --ollama               # after: ollama pull llama3.1:8b-instruct-q4_K_M
cd deploy && docker compose up --build
python -m unittest discover -s tests
modal run gpu/modal_app.py                 # real vLLM on a cloud L4 GPU (see gpu/README.md)
```

## Sample output
```text
Hardware: laptop-m2-16gb · memory budget 12 GB · SLO p95 6000 ms · backend SimulatedBackend (time x0.02)

llama3.1-8b:q4_K_M   mem  4.9 GB · quality 0.81
   c=1   p50   1324 ms  p95   1406 ms  ttft   180 ms    26.4 tok/s  429s 0
   c=4   p50   1386 ms  p95   1437 ms  ttft   180 ms    98.7 tok/s  429s 0
   c=8   p50   2430 ms  p95   2725 ms  ttft  1350 ms   110.2 tok/s  429s 0
   c=16  p50   2602 ms  p95   3974 ms  ttft  1458 ms    76.6 tok/s  429s 35
llama3.1-8b:q8_0     mem  8.5 GB · quality 0.84
   c=1   p50   2054 ms  p95   2058 ms  ttft   260 ms    17.6 tok/s  429s 0
   c=4   p50   2054 ms  p95   3956 ms  ttft   260 ms    53.2 tok/s  429s 0
   c=8   p50   5968 ms  p95   6244 ms  ttft  4161 ms    54.3 tok/s  429s 0
   c=16  p50   5490 ms  p95   7869 ms  ttft  3858 ms    47.7 tok/s  429s 35
llama3.1-8b:fp16     SKIPPED: llama3.1-8b:fp16 needs 16.1 GB > budget 12 GB
qwen2.5-3b:q4_K_M    mem  2.1 GB · quality 0.71
   c=1   p50    758 ms  p95    760 ms  ttft    90 ms    44.9 tok/s  429s 0
   c=4   p50    756 ms  p95    758 ms  ttft    90 ms   181.4 tok/s  429s 0
   c=8   p50    744 ms  p95   1279 ms  ttft    90 ms   171.9 tok/s  429s 0
   c=16  p50   1453 ms  p95   2045 ms  ttft   792 ms   268.8 tok/s  429s 21

Recommendation: llama3.1-8b:q4_K_M (highest quality meeting p95 <= 6000 ms at 8 concurrent with no 429s)

Ops checks:
  switch to broken-model -> HTTP 409: health check failed, staying on llama3.1-8b:q4_K_M: model broken-model:q4 failed to load
  switch to fp16 -> HTTP 409: llama3.1-8b:fp16 needs 16.1 GB > budget 12 GB
  switch to qwen2.5-3b -> HTTP 200: active model is now qwen2.5-3b:q4_K_M (previous llama3.1-8b:q4_K_M)
  rollback -> HTTP 200: rolled back: active model is now llama3.1-8b:q4_K_M (previous qwen2.5-3b:q4_K_M)
  streaming -> 8 SSE chunks + [DONE]=True
  wrong API key -> HTTP 401
  /metrics sample:
    llm_requests_total{model="llama3.1-8b:q4_K_M",status="200"} 58
    llm_requests_total{model="llama3.1-8b:q4_K_M",status="429"} 35
    llm_requests_total{model="llama3.1-8b:q8_0",status="200"} 57
    llm_requests_total{model="llama3.1-8b:q8_0",status="429"} 35
    llm_requests_total{model="qwen2.5-3b:q4_K_M",status="200"} 71
    llm_requests_total{model="qwen2.5-3b:q4_K_M",status="429"} 21

Wrote reports/benchmark.json
```

## Files
| Path | Purpose |
|---|---|
| config/models.json | Profiles, hardware, server settings |
| backends.py | Ollama + simulated backends |
| llm_server.py | OpenAI-compatible gateway |
| benchmark.py | Benchmark + ops checks |
| deploy/ | Docker, compose, Prometheus |
| gpu/ | vLLM GPU benchmark: client, configs, Modal + VM runners, report |

## Documentation
- [docs/PROJECT_EXPLANATION.md](docs/PROJECT_EXPLANATION.md) · [docs/PROJECT_EXPLANATION.docx](docs/PROJECT_EXPLANATION.docx): full explanation
- [docs/PRESENTATION.pptx](docs/PRESENTATION.pptx): slide deck for walkthroughs and interviews
