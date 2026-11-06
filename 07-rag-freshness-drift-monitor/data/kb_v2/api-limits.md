---
owner: platform-team
last_reviewed: 2026-09-20
criticality: medium
---
# API limits

## Rate limits
The public API allows 600 requests per minute per workspace.  Exceeding the limit returns HTTP 429 with a Retry-After header.

## Pagination
List endpoints return up to 100 items per page. Use the next_cursor field to fetch the next page.
