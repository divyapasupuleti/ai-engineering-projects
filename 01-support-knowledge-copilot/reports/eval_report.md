# Support Copilot eval report (38 golden questions)

| Strategy | top1_source_accuracy | source_recall_at_5 | refusal_accuracy | false_refusal_rate | citation_validity | avg_confidence |
|---|---|---|---|---|---|---|
| dense | 93.9% | 100.0% | 100.0% | 3.0% | 100.0% | 0.85 |
| sparse | 97.0% | 100.0% | 100.0% | 0.0% | 100.0% | 0.85 |
| hybrid | 93.9% | 100.0% | 100.0% | 3.0% | 100.0% | 0.85 |
| hybrid+rerank | 97.0% | 100.0% | 100.0% | 0.0% | 100.0% | 0.85 |

## Failures: dense
- q23 top1=release-notes expected=billing-faq
- q35 top1=onboarding-guide expected=troubleshooting-guide

## Failures: sparse
- q23 top1=release-notes expected=billing-faq

## Failures: hybrid
- q23 top1=release-notes expected=billing-faq
- q35 top1=onboarding-guide expected=troubleshooting-guide

## Failures: hybrid+rerank
- q23 top1=release-notes expected=billing-faq
