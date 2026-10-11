---
name: Odds feed behavior
description: The external odds page's rendered table and raw feed format.
---

The odds page's initial HTML does not contain the match rows. Its script fetches a separate feed encoded as a JavaScript-style array; multiple linked rows may represent the same fixture.

**Why:** Parsing only the raw HTML returned no usable fixture table, and treating every feed row as a separate fixture produced duplicates.

**How to apply:** When changing this scraper, inspect the live page script and feed format. Parse the feed rather than expecting the initial HTML to contain matches, and deduplicate by league, teams, and displayed time.
