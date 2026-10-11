---
name: API-Football Free plan
description: H2H query limitations and empty-response errors on the Free plan.
---

The API-Football Free plan rejects the H2H `last` query parameter and may respond with HTTP 200 plus a non-empty `errors` field and an empty `response`.

**Why:** Sending `last=5` made every H2H request appear to return no history even when the teams had prior meetings.

**How to apply:** Omit `last` from H2H requests, trim the returned list locally, and always check `errors` before interpreting an empty `response` as no historical matches.
