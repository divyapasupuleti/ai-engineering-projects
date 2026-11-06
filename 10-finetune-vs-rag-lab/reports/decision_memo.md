# Decision memo: fine-tune vs RAG

## Task A: ticket routing (behaviour, company jargon)

| approach | accuracy | macro-F1 | jargon acc | prompt tokens | $/1k requests |
|---|---|---|---|---|---|
| prompt_only | 83.3% | 0.83 | 53.2% | 220 | 0.0384 |
| rag_few_shot | 92.7% | 0.925 | 83.5% | 420 | 0.0684 |
| fine_tuned | 95.3% | 0.951 | 88.6% | 40 | 0.0228 |

Fine-tune training cost $0.0586; pays back after ~1,285 requests.

## Task B: product facts that change

| approach | before update | after update | on changed facts |
|---|---|---|---|
| prompt_only | 0% | 0% | 0% |
| rag | 100% | 100% | 100% |
| fine_tuned | 97% | 57% | 0% |

## Recommendation

- Routing/format/tone with stable labels and high volume: **fine tuned**.
- Facts, policies and prices: **RAG**; a fine-tune silently serves stale facts until retrained.
- Start with prompt-only + RAG; fine-tune when you have a few hundred labelled examples, stable labels and volume above the break-even point.
