---
source: api-guide
doc_type: api_docs
updated: 2026-07-20
access: public
---
# API Guide

## Rate limits
The public API allows 600 requests per minute per API key. Requests above the limit receive HTTP 429 with a Retry-After header in seconds.

## API key rotation
API keys can be rotated from the Developer settings page. The old key keeps working for 24 hours after rotation so integrations can be updated without downtime.

## Webhooks
Webhooks are signed with an HMAC SHA256 signature in the X-Signature header. Verify the signature with your webhook secret before processing the payload.

## Pagination
List endpoints return 100 items per page by default. Use the cursor value from the response to request the next page.
