# LLM spend report (1000 simulated requests over 3 days)

- Served: 981 · blocked by budget: 19 · budget overrides: 60
- Actual spend: $0.8814 · all-claude-sonnet counterfactual: $2.6691 · **savings 67.0%**
- Monthly projection at this rate: $8.81
- Verifier pass rate: 89.1% on 92 sampled cheap-model responses
- Escalation rate: 1.4%

## Spend by team
| Team | Spend | Daily budget |
|---|---|---|
| engineering | $0.2818 | $0.08 |
| legal | $0.2280 | $1.20 |
| support | $0.1944 | $0.40 |
| sales | $0.1773 | $0.05 |

## Spend by feature
| Feature | Spend |
|---|---|
| contract_review | $0.2280 |
| log_triage | $0.2024 |
| deal_analysis | $0.1682 |
| reply_draft | $0.1261 |
| commit_summary | $0.0794 |
| ticket_tagging | $0.0560 |
| field_extract | $0.0123 |
| crm_cleanup | $0.0091 |

## Model mix and latency
| Model | Requests | p50 ms | p95 ms |
|---|---|---|---|
| claude-haiku | 256 | 1520 | 1940 |
| claude-sonnet | 77 | 3220 | 5160 |
| gpt-4o | 148 | 3340 | 3340 |
| gpt-4o-mini | 500 | 1390 | 1630 |

## Routing misses (sample)
- claude-haiku: claude-haiku below quality bar for difficulty 3
- gpt-4o-mini: gpt-4o-mini below quality bar for difficulty 3
- gpt-4o-mini: gpt-4o-mini below quality bar for difficulty 3
- gpt-4o: gpt-4o below quality bar for difficulty 3
- gpt-4o: gpt-4o below quality bar for difficulty 3

## Budget alerts
- 2026-11-01 [warn] sales at 80% of daily budget
- 2026-11-01 [warn] engineering at 80% of daily budget
- 2026-11-01 [over] sales exceeded daily budget; serving high requests with override
- 2026-11-01 [over] engineering exceeded daily budget; serving normal requests with override
- 2026-11-01 [block] sales hit 100% of daily budget; blocking low-priority requests
- 2026-11-01 [block] engineering hit 100% of daily budget; blocking low-priority requests
- 2026-11-02 [warn] sales at 80% of daily budget
- 2026-11-02 [over] sales exceeded daily budget; serving normal requests with override
- 2026-11-02 [block] sales hit 100% of daily budget; blocking low-priority requests
- 2026-11-02 [warn] engineering at 80% of daily budget
- 2026-11-02 [over] engineering exceeded daily budget; serving normal requests with override
- 2026-11-03 [warn] engineering at 80% of daily budget
- 2026-11-03 [block] engineering hit 100% of daily budget; blocking low-priority requests
- 2026-11-03 [warn] sales at 80% of daily budget
- 2026-11-03 [over] engineering exceeded daily budget; serving normal requests with override
