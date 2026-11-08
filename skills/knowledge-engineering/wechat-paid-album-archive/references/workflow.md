# Authorized WeChat album archive workflow

## Preconditions

- macOS desktop WeChat is installed and the user is logged in.
- The user has already purchased or otherwise legitimately unlocked the target collection.
- Python 3 and Beautiful Soup 4 are available. Check with `python3 -c 'import bs4'`.
- The destination is a local personal-backup directory. Do not place exported paid content in a Git repository.

## 1. Discover public identifiers

Run the public-only helper against the supplied article or collection URL:

```bash
python3 <skill-root>/scripts/discover_album.py '<public-wechat-url>'
```

Record only `album_id`, `biz`, the title, and the sanitized public URL. If the helper cannot discover both identifiers, ask the user to open the collection page normally and copy its `mp/appmsgalbum` URL. Do not obtain identifiers by controlling the WeChat UI.

## 2. Establish a fresh user-authorized session

Ask the user to manually open an unlocked paid article in desktop WeChat, wait until the complete body is visible, and keep the page open. If the cache does not update, ask the user to manually use `File -> Refresh` or open an unseen collection article.

Inspect only cache-file metadata when diagnosing freshness. Never print cached URLs, query strings, cookies, `key`, `exportkey`, or `pass_ticket`.

If WeChat shows a re-login or account-safety prompt, stop all UI automation. The cause may be unverified; treat the prompt itself as the boundary.

## 3. Export in two stages

Use a task-specific output directory outside the skill repository:

```bash
python3 -u <skill-root>/scripts/export_album.py \
  --album-id '<numeric-album-id>' \
  --biz '<public-biz-value>' \
  --publisher '<公众号名称>' \
  --output '<absolute-output-directory>'
```

The exporter first reads the public collection directory, then prefetches every remaining article body before downloading images. This ordering reduces the chance that a short-lived authorized session expires during asset downloads.

The exporter is resumable. Completed articles have `.state/NN.json` records whose hashes must still match the corresponding HTML. Rerunning skips valid completed records and continues missing work.

Do not redirect verbose network traces or environment dumps into the archive. The normal progress output contains titles and counts only.

## 4. Verify the archive

Run the deterministic validator:

```bash
python3 <skill-root>/scripts/validate_archive.py '<absolute-output-directory>'
```

Require `status: ok`. The validator checks:

- article count equals the public collection count;
- every manifest and resume-state hash matches;
- every localized image reference exists;
- paywall/preview markers are absent;
- the offline visibility override is present;
- no session-value pattern appears in deliverables or state;
- `SHA256SUMS` covers metadata, articles, and every asset.

## 5. Browser-render representative samples

Serve the directory only on loopback, then inspect the index plus the first, middle, and last article in a real browser:

```bash
python3 -m http.server 8765 --bind 127.0.0.1 --directory '<absolute-output-directory>'
```

Confirm that headings, text, and images are visible. WeChat commonly emits `#js_content` with `visibility: hidden; opacity: 0` and relies on page JavaScript to reveal it. Because offline copies remove scripts, the generated shell must override both properties with `!important`. A structurally present but visually blank page is a failed verification.

A missing `/favicon.ico` response is harmless. Missing article or asset responses are not.

Stop the loopback server and close the test browser after inspection.

## 6. Package without broadening scope

Create a ZIP only after validation, then test the ZIP's integrity. Keep the editable directory and ZIP as separate artifacts. Do not upload the paid archive unless the user explicitly names and authorizes a private destination.

When publishing this skill to GitHub, include only skill instructions, scripts, metadata, and dependency declarations. Exclude exported articles, `.state`, caches, screenshots, ZIP files, and account/session data. Default to a private repository for session-adjacent automation unless the user explicitly requests public visibility after reviewing the contents.

## Failure handling

- **No fresh authenticated cache record:** ask for one manual open or refresh; do not retry WeChat UI automation.
- **Article reports locked or lacks `#js_content`:** stop. Do not weaken the unlock check.
- **Session expires during acquisition:** keep prefetched bodies and completed state, obtain one new manual refresh, and rerun.
- **Blank offline page:** restore or add the visibility override, update article and state hashes, regenerate checksums, and repeat browser inspection.
- **Failed image downloads:** leave the archive incomplete, preserve the failure list, and rerun before packaging.
