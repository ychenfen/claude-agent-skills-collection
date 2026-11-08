---
name: wechat-paid-album-archive
description: Archive a WeChat Official Account album that the user has already purchased or unlocked into local offline HTML and images. Use for lawful personal backup, interrupted-export recovery, or verification of an existing archive; do not use to bypass payment, automate the WeChat window, or redistribute paid content.
---

# WeChat Paid Album Archive

Create a resumable personal archive with one offline HTML file per article, local images, an index, a manifest, and SHA-256 checksums.

## Non-negotiable boundaries

- Require the user to already have legitimate access to the collection. Stop if an article is still locked or the request is to evade payment or access controls.
- Never automate clicks, refreshes, login, or security prompts in WeChat. If fresh authorization is needed, ask the user to open or manually refresh one unlocked article and keep it open.
- Read session-adjacent cache values only from the current user's local WeChat profile, keep them in memory, and never print, log, save, commit, or return them.
- Treat a re-login or account-safety prompt as a hard boundary. Stop touching that window and switch to read-only diagnosis.
- Keep exported paid content local. A request to publish the skill or code does not authorize uploading the exported articles, `.state`, caches, screenshots, or account data.

## Workflow

Read [references/workflow.md](references/workflow.md) before exporting or repairing an archive. It contains the required discovery, two-stage acquisition, visibility repair, verification, and packaging sequence.

Use the bundled scripts instead of rewriting their logic:

- `scripts/discover_album.py`: derive public `album_id` and `__biz` metadata from an article or collection URL.
- `scripts/export_album.py`: perform the resumable two-stage export without persisting authorization values.
- `scripts/validate_archive.py`: verify counts, article/state hashes, local assets, visibility, paywall removal, checksum coverage, and absence of session-value patterns.

Resolve script paths from this skill directory. Do not assume a particular home-directory layout in reusable commands.

## Completion gate

Report completion only after all expected articles exist, all local references resolve, the browser renders representative first/middle/last articles, `SHA256SUMS` covers articles and assets, and the validator returns `status: ok`. Keep local completion separate from ZIP creation, GitHub publication of the skill, and any external delivery.
