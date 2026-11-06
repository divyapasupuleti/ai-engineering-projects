# AI Engineering Projects

Fifteen production-style AI engineering projects, each runnable offline with the Python standard library.
Every project folder contains code, tests, a README, an architecture diagram, a project explanation (Markdown + Word) and a presentation deck generated from one spec.

| # | Project | Topic | Headline result | Folder |
|---|---|---|---|---|
| 1 | **Support Knowledge Copilot with Verified Citations** | RAG | Built a hybrid-retrieval support copilot (dense + BM25 + RRF + rerank) with claim-level citation verification and calibrated no-answer handling, evaluated on a 38-question golden set with strategy ablations. | [`01-support-knowledge-copilot`](01-support-knowledge-copilot/) |
| 2 | **Prompt Release Safety Gate** | LLMOps | Built a prompt release safety gate in CI that compares production and candidate prompts on a 90-case risk-labelled golden set and blocks merges on schema, safety, cost or latency regressions (caught a candidate with 38 PII leaks and 28x cost). | [`02-prompt-release-safety-gate`](02-prompt-release-safety-gate/) |
| 3 | **LLM Spend Control Center** | LLMOps | Built an LLM spend gateway with complexity-based routing, pre-call team budgets and sampled quality verification; cut simulated spend 67% vs an all-strong-model baseline with an ~89% verifier pass rate. | [`03-llm-spend-control-center`](03-llm-spend-control-center/) |
| 4 | **AI Output Policy Guardrail Service** | Guardrails | Built an LLM output guardrail service with versioned policies, deterministic PII/safety detectors, judge-based claim checks and five decision outcomes, with a full audit trail and policy-change replay. | [`04-ai-output-policy-guardrail`](04-ai-output-policy-guardrail/) |
| 5 | **Production Log-to-Eval Dataset Builder** | Evals | Built a log-to-eval data flywheel that redacts, samples (failure-biased), clusters and auto-labels LLM interactions with human review, producing 122 approved eval cases from 1,000 logs at 77% auto-label acceptance. | [`05-log-to-eval-dataset-builder`](05-log-to-eval-dataset-builder/) |
| 6 | **Permissioned Tool-Using Agent Sandbox** | Agents | Built a permissioned agent runtime with role-based tool access, approval pause/resume, sandboxed tools and prompt-injection taint tracking; 8 adversarial scenarios contained with a full audit trail. | [`06-permissioned-agent-sandbox`](06-permissioned-agent-sandbox/) |
| 7 | **RAG Freshness & Drift Monitor** | RAG | Built a RAG freshness monitor that hashes and classifies source changes, ranks them by traffic impact and rebuilds incrementally, lifting traffic-weighted answer freshness from 39% to 100% while avoiding 44% of embedding cost. | [`07-rag-freshness-drift-monitor`](07-rag-freshness-drift-monitor/) |
| 8 | **Natural Language to API Assistant** | Agents | Built an NL-to-API assistant that retrieves OpenAPI endpoints, plans chained calls, validates against JSON schema and gates writes behind confirmation and roles, passing 16/16 golden workflows including ambiguity and error cases. | [`08-nl-to-api-assistant`](08-nl-to-api-assistant/) |
| 9 | **Multimodal Document Intake Pipeline** | Multimodal | Built a document intake pipeline with OCR quality gating, vision-LLM fallback, OCR repair and business-rule validation, reaching 78% straight-through processing with zero erroneous auto-approvals at $0.003/document. | [`09-multimodal-document-intake`](09-multimodal-document-intake/) |
| 10 | **Fine-Tune vs RAG Decision Lab** | Fine-tuning | Built a fine-tune vs RAG decision lab measuring accuracy, data needs, cost and fact freshness; showed the fine-tune won on routing (95.3% at 3x lower cost) but fell to 0% on changed facts, which RAG kept at 100%. | [`10-finetune-vs-rag-lab`](10-finetune-vs-rag-lab/) |
| 11 | **AI Trace Explorer & Root-Cause Analyzer** | Observability | Built an AI trace explorer with OTel-shaped spans, a 9-category failure taxonomy and owner-routed fix hints; diagnosed 111/111 injected faults, caught a prompt-version regression (3x JSON failures) and exported 90 failures as eval cases. | [`11-ai-trace-explorer`](11-ai-trace-explorer/) |
| 12 | **Semantic Cache Gateway with Safety Validation** | LLMOps | Built a multi-tenant semantic cache gateway with fail-closed scoping, entity/number validation and tag invalidation, cutting LLM cost 58% and p50 latency from 2.6 s to 18 ms with zero wrong hits across 2,000 requests. | [`12-semantic-cache-gateway`](12-semantic-cache-gateway/) |
| 13 | **AI Feature Rollout Monitor** | LLMOps | Built an AI rollout controller with sticky hashing, staged exposure, z-tested quality guardrails and segment analysis; caught a hidden German-locale regression at 25% and auto-rolled back a safety incident with <1% of users exposed. | [`13-ai-feature-rollout-monitor`](13-ai-feature-rollout-monitor/) |
| 14 | **Evaluation-as-a-Service Platform** | Evals | Built an evaluation-as-a-service platform with versioned rubrics, judges calibrated against human labels (kappa 0.734 vs 0.75 human ceiling), threshold tuning that made a 15x cheaper judge viable, and a CI gate that blocked a hidden category regression. | [`14-evaluation-as-a-service`](14-evaluation-as-a-service/) |
| 15 | **Local LLM Deployment Kit** | Deployment | Built a local LLM deployment kit with an OpenAI-compatible gateway, quantization benchmarking, back-pressure, Prometheus metrics and health-checked model switching/rollback; selected a q8 profile meeting a 6 s p95 SLO on a 12 GB host. | [`15-local-llm-deployment-kit`](15-local-llm-deployment-kit/) |

## Each project folder

| File | Contents |
|---|---|
| `README.md` | Goals, architecture, how to run, sample output |
| `docs/ARCHITECTURE.png` | Layered architecture diagram (Mermaid source in the explanation doc) |
| `docs/PROJECT_EXPLANATION.md` / `.docx` | Problem, goals, components, flow, decisions, evaluation, interview talking points |
| `docs/PRESENTATION.pptx` | 11-slide deck with speaker notes |
| `project_spec.py` | Single source for all of the above |
| `tests/` | Unit tests (`python -m unittest discover -s tests`) |

## Quick start

```bash
python run_all_tests.py                     # all project test suites
cd 01-support-knowledge-copilot && python evaluate.py
```

Regenerate docs (needs `pip install -r tools/requirements.txt`):

```bash
MPLCONFIGDIR=/tmp/mpl python tools/build_docs.py        # all projects
python tools/build_docs.py 07 12                         # selected projects
python tools/build_index.py                              # this README
```

## Shared code

`common/` holds small helpers used across projects: hashed embeddings, tokenisation, a model pricing registry, a tracer, JSONL I/O and percentiles. Simulated models and providers are deterministic so every metric in the docs is reproducible; each project's docs say where a real provider plugs in.

## Projects

### 1. Support Knowledge Copilot with Verified Citations

Answers support questions from internal docs, cites every claim, and proves each citation actually supports the claim.

- **Hybrid retrieval over shared chunk ids**: Dense + BM25 fused with RRF; rerank top pool
- **Grounded answers with chunk-level citations**: 100% of answer sentences carry a [chunk_id]
- **Automatic citation verification**: Unsupported citations flagged in could_not_verify
- **Calibrated no-answer behaviour**: Refusal accuracy on unanswerable questions >= 95%
- **Reproducible evaluation**: 38-question golden set, strategy ablation report in reports/

Run: `cd 01-support-knowledge-copilot && python ingest.py --rebuild` · [Explanation](01-support-knowledge-copilot/docs/PROJECT_EXPLANATION.md) · [Slides](01-support-knowledge-copilot/docs/PRESENTATION.pptx) · [Diagram](01-support-knowledge-copilot/docs/ARCHITECTURE.png)

### 2. Prompt Release Safety Gate

A CI gate that runs every prompt change against a curated golden set and blocks the merge when quality, safety, cost or latency regress.

- **Version prompts as reviewable files**: prompts/*.json with version, owner, model, rules, few-shot
- **Enforce the output contract**: Schema validity measured per case; prose-wrapped JSON fails
- **Curated, versioned golden set**: 90 cases with risk_area + why_this_case_exists + CHANGELOG
- **Multi-dimensional comparison**: Schema, field accuracy, safety, cost, p95 latency, regressions
- **Automated release decision**: BLOCK exits 1 in CI; WARN allows merge with a visible note

Run: `cd 02-prompt-release-safety-gate && python evals/build_golden.py` · [Explanation](02-prompt-release-safety-gate/docs/PROJECT_EXPLANATION.md) · [Slides](02-prompt-release-safety-gate/docs/PRESENTATION.pptx) · [Diagram](02-prompt-release-safety-gate/docs/ARCHITECTURE.png)

### 3. LLM Spend Control Center

A gateway in front of every LLM call that routes by complexity, enforces team budgets before the call, and proves the savings did not cost quality.

- **Single gateway contract**: One request/response schema across OpenAI, Anthropic and local models
- **Complexity-based routing**: Tier 1-3 classifier with feature overrides in config
- **Budget enforcement**: Warn at 80%, block low priority at 100%, override for normal/high
- **Quality-safe savings**: 10% async verification sample; routing misses recorded
- **Cost visibility**: Spend by team/feature, projection, savings vs all-strong counterfactual

Run: `cd 03-llm-spend-control-center && python simulate.py --requests 1000` · [Explanation](03-llm-spend-control-center/docs/PROJECT_EXPLANATION.md) · [Slides](03-llm-spend-control-center/docs/PRESENTATION.pptx) · [Diagram](03-llm-spend-control-center/docs/ARCHITECTURE.png)

### 4. AI Output Policy Guardrail Service

A policy enforcement layer that reviews every LLM output and approves, warns, rewrites, blocks, or routes it to a human, with an audit record for each decision.

- **Policies as versioned config**: policies.v1/v2.json with severity, detector, action
- **Cheap deterministic checks first**: Schema, PII (Luhn-checked cards), keywords; sub-millisecond
- **Judge for nuanced policies**: Unsupported numeric claims vs context; two passes for high-risk features
- **Five clear outcomes**: approve, approve_with_warning, rewrite, human_review, block
- **Full auditability**: Every decision stored with input/output hashes, policy version, findings, latency

Run: `cd 04-ai-output-policy-guardrail && python demo.py` · [Explanation](04-ai-output-policy-guardrail/docs/PROJECT_EXPLANATION.md) · [Slides](04-ai-output-policy-guardrail/docs/PRESENTATION.pptx) · [Diagram](04-ai-output-policy-guardrail/docs/ARCHITECTURE.png)

### 5. Production Log-to-Eval Dataset Builder

A nightly pipeline that mines LLM logs for high-value interactions, turns them into labelled eval cases, and routes uncertain labels to human review.

- **Unified, redacted log schema**: Emails, phones, secrets removed with method recorded per field
- **Risk-aware sampling**: random, failure_biased (70% failure quota), diversity modes
- **Discover interaction patterns**: Per-feature k-means clusters with readable labels
- **Auto-label with confidence**: Golden answer / rubric / expected refusal + assertions
- **Human-in-the-loop dataset**: Draft -> approved / rejected; edits tracked; JSONL export

Run: `cd 05-log-to-eval-dataset-builder && python generate_logs.py --n 1000` · [Explanation](05-log-to-eval-dataset-builder/docs/PROJECT_EXPLANATION.md) · [Slides](05-log-to-eval-dataset-builder/docs/PRESENTATION.pptx) · [Diagram](05-log-to-eval-dataset-builder/docs/ARCHITECTURE.png)

### 6. Permissioned Tool-Using Agent Sandbox

An agent runtime where every tool call is checked against role, schema, rate limit and risk; high-risk actions pause for approval and resume from persisted state.

- **Typed tool registry**: Each tool declares params, risk, roles, rate limit, write flag
- **Policy check before every call**: allow / needs_approval / deny with a reason code
- **Pause and resume**: Run state persisted as JSON; approver role checked on resume
- **Sandboxed tools**: AST-only calculator; file reads confined to workspace/
- **Injection containment**: Untrusted output scanned; later writes require approval

Run: `cd 06-permissioned-agent-sandbox && python demo.py` · [Explanation](06-permissioned-agent-sandbox/docs/PROJECT_EXPLANATION.md) · [Slides](06-permissioned-agent-sandbox/docs/PRESENTATION.pptx) · [Diagram](06-permissioned-agent-sandbox/docs/ARCHITECTURE.png)

### 7. RAG Freshness & Drift Monitor

Detects when the deployed RAG index has fallen behind its source documents, ranks changes by business impact, and proves an incremental rebuild fixes the stale answers.

- **Content manifest with hashes**: Per-chunk sha256 of normalised text; whitespace-only edits ignored
- **Classify each change**: cosmetic / minor / material using numbers, polarity words, semantic shift
- **Rank by impact**: severity x criticality x probe traffic
- **Prove drift with probes**: Deployed vs candidate answers; stale answers counted by traffic
- **Cheap incremental rebuild**: Re-embed only material/minor/added chunks; report cost avoided

Run: `cd 07-rag-freshness-drift-monitor && python monitor.py` · [Explanation](07-rag-freshness-drift-monitor/docs/PROJECT_EXPLANATION.md) · [Slides](07-rag-freshness-drift-monitor/docs/PRESENTATION.pptx) · [Diagram](07-rag-freshness-drift-monitor/docs/ARCHITECTURE.png)

### 8. Natural Language to API Assistant

Turns requests like 'refund 200 EUR for Umbrella Health' into retrieved, planned, schema-validated and confirmed chains of real API calls.

- **Retrieve relevant endpoints**: Top-3 endpoint cards from the OpenAPI spec; recall@3 = 14/14
- **Plan chained calls**: IDs flow between steps via $N references
- **Validate before calling**: JSON-schema checks: required, enum, min/max, length
- **Safe execution**: Dry-run; confirmation for writes; DELETE admin-only
- **Golden workflow suite**: 16 workflows incl. ambiguity, not-found, invalid enum, API errors

Run: `cd 08-nl-to-api-assistant && python run_workflows.py` · [Explanation](08-nl-to-api-assistant/docs/PROJECT_EXPLANATION.md) · [Slides](08-nl-to-api-assistant/docs/PRESENTATION.pptx) · [Diagram](08-nl-to-api-assistant/docs/ARCHITECTURE.png)

### 9. Multimodal Document Intake Pipeline

Reads scanned invoices, receipts and purchase orders, falls back to a vision model only when OCR is unreliable, validates against business rules and routes by field confidence.

- **OCR quality gate**: Mean token confidence < 0.75 triggers vision fallback
- **Typed extraction per document type**: Invoice (10 fields), receipt (4), PO (4) with normalisation
- **Repair OCR confusions**: O->0, l->1, S->5, B->8 in numeric fields, logged
- **Business rules**: Totals add up, VAT 23%, dates, VAT-id format, PO in ERP, duplicates
- **Zero-escape routing**: Auto-approve only if all fields >= 0.85 and rules pass

Run: `cd 09-multimodal-document-intake && python generate_docs.py --n 80` · [Explanation](09-multimodal-document-intake/docs/PROJECT_EXPLANATION.md) · [Slides](09-multimodal-document-intake/docs/PRESENTATION.pptx) · [Diagram](09-multimodal-document-intake/docs/ARCHITECTURE.png)

### 10. Fine-Tune vs RAG Decision Lab

A reproducible lab that answers 'should we fine-tune or use RAG?' with numbers: accuracy, jargon handling, data needed, cost per request, break-even and behaviour after facts change.

- **Same task, three approaches**: Prompt-only vs RAG few-shot vs trained weights
- **Honest generalisation**: One phrasing per queue held out of training
- **Measure data needs**: Learning curve at 25/50/100/200/400 examples
- **Cost model**: $/1k requests, latency, training cost and break-even volume
- **Knowledge freshness test**: Accuracy after 4 of 10 facts change, without retraining

Run: `cd 10-finetune-vs-rag-lab && python lab.py` · [Explanation](10-finetune-vs-rag-lab/docs/PROJECT_EXPLANATION.md) · [Slides](10-finetune-vs-rag-lab/docs/PRESENTATION.pptx) · [Diagram](10-finetune-vs-rag-lab/docs/ARCHITECTURE.png)

### 11. AI Trace Explorer & Root-Cause Analyzer

Traces every step of an AI workflow, classifies what went wrong, points at the span that caused it, and turns failures into eval cases.

- **Step-level tracing**: OpenTelemetry-shaped spans with parent ids and attributes in SQLite
- **Failure taxonomy**: 9 categories with owner and suggested fix
- **Root cause per trace**: Highest-severity, earliest finding; 100% vs injected faults
- **Regression detection**: Error rate and categories by prompt version
- **Close the loop**: Failing traces exported as draft eval cases

Run: `cd 11-ai-trace-explorer && python explorer.py demo` · [Explanation](11-ai-trace-explorer/docs/PROJECT_EXPLANATION.md) · [Slides](11-ai-trace-explorer/docs/PRESENTATION.pptx) · [Diagram](11-ai-trace-explorer/docs/ARCHITECTURE.png)

### 12. Semantic Cache Gateway with Safety Validation

An LLM gateway cache that reuses answers for paraphrased questions while proving it never serves the wrong tenant, entity or stale price.

- **Two-tier cache**: Exact hash, then semantic similarity within scope
- **Scoped by default**: global / tenant / user scope; fail closed on personal or account words
- **Hit validation**: Numbers, entities and negation must match before reuse
- **TTL + tag invalidation**: pricing 24h, docs 7d, account 1h, real-time never cached
- **Measured safety**: Ground-truth answer ids; wrong-hit count per config and threshold

Run: `cd 12-semantic-cache-gateway && python simulate.py` · [Explanation](12-semantic-cache-gateway/docs/PROJECT_EXPLANATION.md) · [Slides](12-semantic-cache-gateway/docs/PRESENTATION.pptx) · [Diagram](12-semantic-cache-gateway/docs/ARCHITECTURE.png)

### 13. AI Feature Rollout Monitor

Ships a new model or prompt through 1% -> 5% -> 25% -> 50% -> 100% with statistical quality checks, segment analysis, automatic pause/rollback and a full audit trail.

- **Sticky, monotonic assignment**: Consistent hashing; raising % only adds users
- **Staged rollout**: 1 / 5 / 25 / 50 / 100% with minimum samples per stage
- **Statistical guardrails**: One-sided z-tests on bad-answer and thumbs-down rates
- **Segment analysis**: Per-locale and per-plan tests catch hidden regressions
- **Automatic actions + audit**: promote / hold / pause / rollback, every decision logged

Run: `cd 13-ai-feature-rollout-monitor && python simulate.py` · [Explanation](13-ai-feature-rollout-monitor/docs/PROJECT_EXPLANATION.md) · [Slides](13-ai-feature-rollout-monitor/docs/PRESENTATION.pptx) · [Diagram](13-ai-feature-rollout-monitor/docs/ARCHITECTURE.png)

### 14. Evaluation-as-a-Service Platform

A shared evaluation service: versioned rubrics, LLM judges calibrated against human labels, batch runs with history, and a release gate any team can call from CI or HTTP.

- **Versioned rubrics**: Weighted criteria, scale, pass mark and judge prompt in JSON
- **Calibrate judges vs humans**: kappa, MAE, Spearman, bias; human-human agreement as ceiling
- **Tune the pass threshold**: Per judge, to maximise agreement with human pass/fail
- **Batch runs with history**: SQLite runs + per-item results; compare runs
- **Gate + API**: CLI exit code for CI; HTTP POST /evaluate, GET /runs

Run: `cd 14-evaluation-as-a-service && python generate_data.py` · [Explanation](14-evaluation-as-a-service/docs/PROJECT_EXPLANATION.md) · [Slides](14-evaluation-as-a-service/docs/PRESENTATION.pptx) · [Diagram](14-evaluation-as-a-service/docs/ARCHITECTURE.png)

### 15. Local LLM Deployment Kit

An OpenAI-compatible gateway for local models with quantization benchmarking, back-pressure, Prometheus metrics, health-checked model switching and one-command rollback.

- **OpenAI-compatible API**: /v1/chat/completions (incl. SSE streaming), /v1/models, API keys
- **Quantization benchmark**: p50/p95, TTFT, tokens/s, 429s at 1/4/8/16 concurrency per profile
- **Fit to hardware + SLO**: Memory budget and p95 SLO pick the highest-quality profile
- **Safe operations**: Health-checked switch, memory guard, rollback, back-pressure (429)
- **Observable**: Prometheus counters, latency histogram, inflight gauge; docker-compose with Ollama + Prometheus

Run: `cd 15-local-llm-deployment-kit && python benchmark.py                       # simulator` · [Explanation](15-local-llm-deployment-kit/docs/PROJECT_EXPLANATION.md) · [Slides](15-local-llm-deployment-kit/docs/PRESENTATION.pptx) · [Diagram](15-local-llm-deployment-kit/docs/ARCHITECTURE.png)
