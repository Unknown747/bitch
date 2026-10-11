---
name: FotMob access policy
description: The user's source choice and limits for the unofficial FotMob endpoints.
---

The user chose to use FotMob's unofficial endpoints after being told that FotMob does not support regular automated access. They asked how to reduce blocking risk.

**Why:** FotMob's API page says automated or regular systematic use is not permitted; the user still chose the endpoints for this project.

**How to apply:** Keep request volume low with caching and pacing, stop on access-denied or rate-limit responses, honor `Retry-After`, and never bypass restrictions with proxies or IP rotation. These steps reduce unnecessary traffic but do not make recurring automated use permitted or guarantee access.
