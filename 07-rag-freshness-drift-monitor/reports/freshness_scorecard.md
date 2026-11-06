# RAG freshness scorecard

- Date: 2026-11-06
- Verdict: **REBUILD NOW**
- Traffic-weighted freshness: 39% deployed, 100% after rebuild
- Re-embedded 5/9 chunks

## Prioritised changes

| priority | chunk | kind | severity | semantic change | reason |
|---|---|---|---|---|---|
| 26.1 | pricing#plans | modified | material | 0.018 | numeric fact changed ['25 -> 29'] |
| 22.5 | refunds#refund-window | modified | material | 0.041 | numeric fact changed ['30 -> 14'] |
| 16.2 | pricing#annual-billing | modified | material | 0.045 | numeric fact changed ['15% -> 20%'] |
| 8.1 | sso#scim-provisioning | modified | material | 0.521 | polarity words changed: ['not', 'now']  |
| 6.0 | data-export#export-api | added | material | 1.0 | new chunk not yet indexed  |
| 4.65 | legacy-export#csv-export | removed | material | 1.0 | chunk deleted at source  |
| 0.0 | refunds#how-to-request | modified | cosmetic | 0.043 | typo / whitespace only  |

## Probes

| probe | deployed answer | candidate answer | stale | fixed |
|---|---|---|---|---|
| p01 | The Pro plan costs 25 EUR per user per month. | The Pro plan costs 29 EUR per user per month. | True | True |
| p02 | Annual billing gives a 15% discount compared with monthly billing. | Annual billing gives a 20% discount compared with monthly billing. | True | True |
| p03 | Monthly plans can be refunded within 30 days of the charge. | Monthly plans can be refunded within 14 days of the charge. | True | True |
| p04 | Refunds are processed in 5 to 7 bussiness days. | Refunds are processed in 5 to 7 business days. | False | True |
| p05 | SCIM user provisioning is not supported. | SCIM user provisioning is now supported on the Enterprise plan. | True | True |
| p06 | SAML SSO is available on the Enterprise plan only. | SAML SSO is available on the Enterprise plan only. | False | True |
| p07 | The public API allows 600 requests per minute per workspace. | The public API allows 600 requests per minute per workspace. | False | True |
| p08 | List endpoints return up to 100 items per page. | List endpoints return up to 100 items per page. | False | True |
| p09 | Export workspace data as CSV from Settings > Export. | Workspace exports now run through the POST /v2/exports endpoint and ar | True | True |
| p10 | The Starter plan costs 10 EUR per user per month. | The Starter plan costs 10 EUR per user per month. | False | True |

## Owners to notify

- sso: identity-team, last reviewed 340 days ago
