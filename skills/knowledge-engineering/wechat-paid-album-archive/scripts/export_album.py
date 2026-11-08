#!/usr/bin/env python3
"""Export one legitimately unlocked WeChat paid album without persisting auth data."""

from __future__ import annotations

import argparse
import hashlib
import html as html_lib
import json
import mimetypes
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup


ALBUM_ID = ""
BIZ = ""
ALBUM_URL = ""
PUBLISHER = ""
CACHE_MAX_AGE_MINUTES = 30
CACHE_ROOT = Path.home() / "Library/Containers/com.tencent.xinWeChat/Data/Documents/app_data/radium/web/profiles"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 MicroMessenger/7.0.20 MacWechat/3.8.7"
)
AUTH_KEYS = (
    "key",
    "ascene",
    "uin",
    "devicetype",
    "version",
    "lang",
    "countrycode",
    "exportkey",
    "acctmode",
    "pass_ticket",
    "wx_header",
)

ROOT = Path.cwd()
ARTICLES_DIR = ROOT / "articles"
ASSETS_DIR = ROOT / "assets"
STATE_DIR = ROOT / ".state"
PREFETCH_DIR = STATE_DIR / "prefetch"
FAILED_ASSETS: list[dict[str, str]] = []


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Archive one WeChat paid album that the current macOS user has already unlocked. "
            "Authentication values are read from the local WeChat cache and are never persisted."
        )
    )
    parser.add_argument("--album-id", required=True, help="Numeric WeChat album ID")
    parser.add_argument("--biz", required=True, help="Public-account __biz value")
    parser.add_argument("--output", required=True, type=Path, help="Destination directory")
    parser.add_argument("--publisher", default="微信公众号", help="Publisher label used in README metadata")
    parser.add_argument(
        "--cache-root",
        type=Path,
        default=CACHE_ROOT,
        help="WeChat Chromium profile root; defaults to the current macOS user's WeChat container",
    )
    parser.add_argument(
        "--cache-max-age-minutes",
        type=int,
        default=30,
        help="Reject authenticated cache entries older than this many minutes; use 0 to disable the age limit",
    )
    args = parser.parse_args()
    if not args.album_id.isdigit():
        parser.error("--album-id must contain digits only")
    if args.cache_max_age_minutes < 0:
        parser.error("--cache-max-age-minutes cannot be negative")
    return args


def configure(args: argparse.Namespace) -> None:
    global ALBUM_ID, BIZ, ALBUM_URL, PUBLISHER, CACHE_ROOT, CACHE_MAX_AGE_MINUTES
    global ROOT, ARTICLES_DIR, ASSETS_DIR, STATE_DIR, PREFETCH_DIR
    ALBUM_ID = args.album_id
    BIZ = args.biz
    PUBLISHER = args.publisher
    CACHE_ROOT = args.cache_root.expanduser().resolve()
    CACHE_MAX_AGE_MINUTES = args.cache_max_age_minutes
    ROOT = args.output.expanduser().resolve()
    ARTICLES_DIR = ROOT / "articles"
    ASSETS_DIR = ROOT / "assets"
    STATE_DIR = ROOT / ".state"
    PREFETCH_DIR = STATE_DIR / "prefetch"
    ALBUM_URL = "https://mp.weixin.qq.com/mp/appmsgalbum?" + urlencode(
        {"__biz": BIZ, "action": "getalbum", "album_id": ALBUM_ID}
    )


def request_bytes(url: str, *, referer: str | None = None, timeout: int = 45) -> bytes:
    headers = {"User-Agent": UA, "Accept-Encoding": "identity"}
    if referer:
        headers["Referer"] = referer
    req = Request(url, headers=headers)
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def clean_source_url(url: str) -> str:
    parts = urlsplit(html_lib.unescape(url).replace("http://", "https://", 1))
    allowed = {"__biz", "mid", "idx", "sn", "chksm"}
    query = [(k, v) for k, v in parse_qsl(parts.query) if k in allowed]
    return urlunsplit(("https", "mp.weixin.qq.com", "/s", urlencode(query), ""))


def load_album_directory() -> tuple[dict, list[dict]]:
    page = request_bytes(ALBUM_URL).decode("utf-8", "replace")
    soup = BeautifulSoup(page, "html.parser")
    title_node = soup.select_one("#js_tag_name")
    title = title_node.get_text(" ", strip=True) if title_node else "微信付费合集"
    count_match = re.search(r"article_count:\s*'(\d+)'", page)
    expected = int(count_match.group(1)) if count_match else 0

    items: list[dict] = []
    for node in soup.select("li.album__list-item[data-link]"):
        url = clean_source_url(node.get("data-link", ""))
        q = dict(parse_qsl(urlsplit(url).query))
        ts_node = node.select_one(".js_article_create_time")
        items.append(
            {
                "title": node.get("data-title", "").strip(),
                "url": url,
                "msgid": node.get("data-msgid") or q.get("mid", ""),
                "itemidx": node.get("data-itemidx") or q.get("idx", ""),
                "create_time": ts_node.get_text(strip=True) if ts_node else "",
            }
        )

    while items:
        last = items[-1]
        api_url = "https://mp.weixin.qq.com/mp/appmsgalbum?" + urlencode(
            {
                "action": "getalbum",
                "__biz": BIZ,
                "album_id": ALBUM_ID,
                "count": 10,
                "begin_msgid": last["msgid"],
                "begin_itemidx": last["itemidx"],
                "f": "json",
            }
        )
        data = json.loads(request_bytes(api_url, referer=ALBUM_URL))
        resp = data.get("getalbum_resp") or {}
        batch = resp.get("article_list") or []
        if isinstance(batch, dict):
            batch = [batch]
        if not batch:
            break
        before = len(items)
        seen = {(x["msgid"], x["itemidx"]) for x in items}
        for raw in batch:
            key = (str(raw.get("msgid", "")), str(raw.get("itemidx", "")))
            if key in seen:
                continue
            items.append(
                {
                    "title": str(raw.get("title", "")).strip(),
                    "url": clean_source_url(str(raw.get("url", ""))),
                    "msgid": key[0],
                    "itemidx": key[1],
                    "create_time": str(raw.get("create_time", "")),
                }
            )
            seen.add(key)
        if len(items) == before or int(resp.get("continue_flag", 0)) != 1:
            break

    if expected and len(items) != expected:
        raise RuntimeError(f"album directory incomplete: expected {expected}, got {len(items)}")
    return {"title": title, "article_count": expected or len(items), "url": ALBUM_URL}, items


def find_auth_query() -> dict[str, str]:
    candidates: list[tuple[float, dict[str, str]]] = []
    cutoff = time.time() - CACHE_MAX_AGE_MINUTES * 60 if CACHE_MAX_AGE_MINUTES else 0
    for path in CACHE_ROOT.glob("multitab_*/Cache/Cache_Data/*_0"):
        try:
            mtime = path.stat().st_mtime
            if cutoff and mtime < cutoff:
                continue
            with path.open("rb") as fh:
                head = fh.read(65536)
        except OSError:
            continue
        # The same account session can be cached from a directly opened article,
        # where cur_album_id is absent even though the paid content is unlocked.
        if b"exportkey=" not in head or b"pass_ticket=" not in head:
            continue
        start = head.find(b"https://mp.weixin.qq.com/s?")
        end = head.find(b"\x1f\x8b\x08", start)
        if start < 0 or end < 0:
            continue
        try:
            cached_url = head[start:end].decode("ascii")
            query = dict(parse_qsl(urlsplit(cached_url).query, keep_blank_values=True))
        except (UnicodeDecodeError, ValueError):
            continue
        if all(query.get(k) for k in ("key", "uin", "exportkey", "pass_ticket")):
            candidates.append((mtime, query))
    if not candidates:
        raise RuntimeError(
            "no fresh authenticated paid-article cache entry found; manually open or refresh one "
            "unlocked article in WeChat, keep it open, and rerun without automating the WeChat window"
        )
    return max(candidates, key=lambda item: item[0])[1]


def authenticated_url(source_url: str, auth: dict[str, str]) -> str:
    parts = urlsplit(source_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update({"scene": "178", "cur_album_id": ALBUM_ID})
    for key in AUTH_KEYS:
        if auth.get(key):
            query[key] = auth[key]
    return urlunsplit(("https", "mp.weixin.qq.com", "/s", urlencode(query), "rd"))


def safe_slug(value: str, limit: int = 76) -> str:
    value = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", value).strip(" ._")
    value = re.sub(r"\s+", " ", value)
    return value[:limit] or "untitled"


def extension_for(url: str, content_type: str) -> str:
    query = dict(parse_qsl(urlsplit(url).query))
    fmt = query.get("wx_fmt", "").lower().replace("jpeg", "jpg")
    if fmt in {"jpg", "png", "gif", "webp", "svg", "avif"}:
        return "." + fmt
    ext = mimetypes.guess_extension(content_type.split(";", 1)[0].strip()) or ""
    return ".jpg" if ext == ".jpe" else (ext or ".bin")


def download_asset(url: str, referer: str) -> tuple[str, Path | None, str | None]:
    url = html_lib.unescape(url.strip())
    if url.startswith("//"):
        url = "https:" + url
    if url.startswith("http://"):
        url = "https://" + url[7:]
    if not url.startswith("https://"):
        return url, None, "unsupported URL"
    digest = hashlib.sha256(url.encode()).hexdigest()[:24]
    existing = next(ASSETS_DIR.glob(digest + ".*"), None)
    if existing and existing.stat().st_size > 0:
        return url, existing, None
    try:
        req = Request(url, headers={"User-Agent": UA, "Referer": referer, "Accept-Encoding": "identity"})
        with urlopen(req, timeout=45) as resp:
            body = resp.read()
            ctype = resp.headers.get("Content-Type", "application/octet-stream")
        if not body:
            raise ValueError("empty response")
        ext = extension_for(url, ctype)
        target = ASSETS_DIR / f"{digest}{ext}"
        target.write_bytes(body)
        return url, target, None
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
        return url, None, f"{type(exc).__name__}: {exc}"


def localize_content(content: BeautifulSoup, source_url: str) -> tuple[int, list[str]]:
    for node in content.select(".js_pay_preview_filter, mp-pay-preview-filter, script"):
        node.decompose()

    jobs: list[tuple[object, str, str]] = []
    for img in content.find_all("img"):
        src = img.get("data-src") or img.get("src")
        if src and not src.startswith("data:"):
            jobs.append((img, "src", src))
    for node in content.find_all(style=re.compile(r"url\(")):
        style = node.get("style", "")
        for match in re.findall(r"url\([\"']?([^\"')]+)", style):
            if match and not match.startswith("data:"):
                jobs.append((node, "style", match))

    results: dict[str, tuple[Path | None, str | None]] = {}
    unique = sorted({job[2] for job in jobs})
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(download_asset, url, source_url): url for url in unique}
        for future in as_completed(futures):
            original, path, error = future.result()
            results[original] = (path, error)
            if error:
                FAILED_ASSETS.append({"url": original, "error": error})

    localized: list[str] = []
    for node, kind, original in jobs:
        path, error = results.get(original, (None, "not attempted"))
        if not path:
            continue
        rel = "../assets/" + path.name
        localized.append(rel)
        if kind == "src":
            node["src"] = rel
            node.attrs.pop("data-src", None)
            node.attrs.pop("srcset", None)
            node.attrs.pop("data-srcset", None)
            node.attrs["loading"] = "lazy"
        else:
            node["style"] = node.get("style", "").replace(original, rel)
    return len(set(localized)), sorted(set(localized))


def article_shell(title: str, author: str, date_text: str, source_url: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html_lib.escape(title)}</title>
<style>
body{{margin:0;background:#f3f5f7;color:#222;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}}
main{{box-sizing:border-box;max-width:900px;margin:24px auto;padding:32px;background:#fff;box-shadow:0 1px 8px #0001}}
h1{{font-size:26px;line-height:1.35;margin:0 0 10px}}.meta{{color:#777;font-size:14px;margin-bottom:28px}}
.source{{margin-left:12px}}#js_content{{visibility:visible!important;opacity:1!important;font-size:16px;line-height:1.75;overflow-wrap:anywhere}}
#js_content img{{display:block;max-width:100%!important;height:auto!important;margin:10px auto}}
#js_content table{{max-width:100%;overflow:auto}}a{{color:#576b95}}@media(max-width:720px){{main{{margin:0;padding:18px;box-shadow:none}}}}
</style></head><body><main>
<h1>{html_lib.escape(title)}</h1>
<div class="meta">{html_lib.escape(author)}　{html_lib.escape(date_text)}
<a class="source" href="{html_lib.escape(source_url)}">原文链接</a></div>
{body}
</main></body></html>
"""


def prefetch_article(index: int, item: dict, auth: dict[str, str]) -> None:
    source_url = item["url"]
    body = request_bytes(authenticated_url(source_url, auth), referer=ALBUM_URL)
    text = body.decode("utf-8", "replace")
    is_paid = bool(re.search(r"is_paid:\s*'1'\s*\*\s*1", text))
    has_paywall = "mp-pay-preview-filter" in text or "js_pay_preview_filter" in text
    # Some older entries in a paid album are ordinary free articles. They have
    # is_paid=0 because no purchase is required, and contain no preview filter.
    if not is_paid and has_paywall:
        raise RuntimeError(f"article is not unlocked: {item['title']}")
    soup = BeautifulSoup(text, "html.parser")
    content = soup.select_one("#js_content")
    if not content:
        raise RuntimeError(f"article body missing: {item['title']}")
    title_meta = soup.select_one('meta[property="og:title"]')
    title = title_meta.get("content", "").strip() if title_meta else item["title"]
    author_meta = soup.select_one('meta[name="author"]')
    author = author_meta.get("content", PUBLISHER).strip() if author_meta else PUBLISHER
    date_node = soup.select_one("#publish_time")
    date_text = date_node.get_text(" ", strip=True) if date_node else ""
    if not date_text and item.get("create_time", "").isdigit():
        date_text = datetime.fromtimestamp(int(item["create_time"])).strftime("%Y-%m-%d %H:%M")

    for node in content.select(".js_pay_preview_filter, mp-pay-preview-filter, script"):
        node.decompose()
    payload = {
        "title": title,
        "author": author,
        "published": date_text,
        "source_url": source_url,
    }
    PREFETCH_DIR.mkdir(parents=True, exist_ok=True)
    (PREFETCH_DIR / f"{index:02d}.html").write_text(str(content), encoding="utf-8")
    (PREFETCH_DIR / f"{index:02d}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def export_article(index: int, item: dict, auth: dict[str, str]) -> dict:
    content_path = PREFETCH_DIR / f"{index:02d}.html"
    payload_path = PREFETCH_DIR / f"{index:02d}.json"
    if not content_path.exists() or not payload_path.exists():
        prefetch_article(index, item, auth)
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    content = BeautifulSoup(content_path.read_text(encoding="utf-8"), "html.parser")
    title = payload["title"]
    author = payload["author"]
    date_text = payload["published"]
    source_url = payload["source_url"]

    image_count, assets = localize_content(content, source_url)
    clean_text = " ".join(content.get_text(" ", strip=True).split())
    filename = f"{index:02d}_{safe_slug(title)}.html"
    target = ARTICLES_DIR / filename
    target.write_text(article_shell(title, author, date_text, source_url, str(content)), encoding="utf-8")
    sha256 = hashlib.sha256(target.read_bytes()).hexdigest()
    return {
        "index": index,
        "title": title,
        "author": author,
        "published": date_text,
        "source_url": source_url,
        "file": "articles/" + filename,
        "text_chars": len(clean_text),
        "image_count": image_count,
        "assets": assets,
        "sha256": sha256,
    }


def write_index(album: dict, records: list[dict]) -> None:
    rows = []
    for record in records:
        rows.append(
            f'<li><a href="{html_lib.escape(record["file"])}">'
            f'{record["index"]:02d}. {html_lib.escape(record["title"])}</a>'
            f'<span>{html_lib.escape(record["published"])} · {record["image_count"]} 张图</span></li>'
        )
    page = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html_lib.escape(album['title'])}</title>
<style>body{{max-width:900px;margin:36px auto;padding:0 20px;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif;color:#222}}h1{{font-size:28px}}.note{{color:#666}}ol{{padding:0;list-style:none}}li{{padding:13px 0;border-bottom:1px solid #eee}}a{{color:#1756a9;text-decoration:none}}li span{{float:right;color:#888;font-size:13px}}@media(max-width:720px){{li span{{display:block;float:none;margin-top:4px}}}}</style>
</head><body><h1>{html_lib.escape(album['title'])}</h1><p class="note">本地个人备份，共 {len(records)} 篇。请勿公开传播。</p><ol>{''.join(rows)}</ol></body></html>"""
    (ROOT / "index.html").write_text(page, encoding="utf-8")


def write_readme(album: dict, records: list[dict]) -> None:
    text = f"""# {album['title']}

- 导出时间：{datetime.now().astimezone().isoformat(timespec='seconds')}
- 公众号：{PUBLISHER}
- 合集 ID：{ALBUM_ID}
- 文章数量：{len(records)}
- 格式：离线 HTML + 本地图片
- 入口：`index.html`

这是使用本人已兑换微信账号生成的本地个人备份。导出文件不含微信登录参数、Cookie、`key`、`exportkey` 或 `pass_ticket`，请勿公开传播。

验证边界：文章正文已以付费解锁状态获取；目录数量与公众号合集页面一致。动态评论、点赞数、音视频播放能力及微信内交互没有离线化。
"""
    (ROOT / "README.md").write_text(text, encoding="utf-8")


def write_checksums() -> None:
    files = [ROOT / "README.md", ROOT / "index.html", ROOT / "manifest.json"]
    files.extend(sorted(ARTICLES_DIR.glob("*.html")))
    files.extend(sorted(path for path in ASSETS_DIR.iterdir() if path.is_file()))
    lines = []
    for path in files:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.relative_to(ROOT)}")
    (ROOT / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    configure(parse_args())
    for directory in (ROOT, ARTICLES_DIR, ASSETS_DIR, STATE_DIR, PREFETCH_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    print("[1/4] Reading the public album directory...")
    album, items = load_album_directory()
    print(f"      Found {len(items)} articles.")
    print("[2/4] Reusing the locally authenticated WeChat session (not persisted)...")
    auth = find_auth_query()

    pending_prefetch = []
    for index, item in enumerate(items, 1):
        state_path = STATE_DIR / f"{index:02d}.json"
        content_path = PREFETCH_DIR / f"{index:02d}.html"
        payload_path = PREFETCH_DIR / f"{index:02d}.json"
        if not state_path.exists() and (not content_path.exists() or not payload_path.exists()):
            pending_prefetch.append((index, item))
    if pending_prefetch:
        print(f"      Prefetching {len(pending_prefetch)} remaining article bodies before the session expires...")
        for index, item in pending_prefetch:
            print(f"[P{index:02d}/{len(items):02d}] fetch   {item['title']}")
            prefetch_article(index, item, auth)

    records: list[dict] = []
    for index, item in enumerate(items, 1):
        state_path = STATE_DIR / f"{index:02d}.json"
        if state_path.exists():
            record = json.loads(state_path.read_text(encoding="utf-8"))
            article_path = ROOT / record["file"]
            if article_path.exists() and hashlib.sha256(article_path.read_bytes()).hexdigest() == record["sha256"]:
                records.append(record)
                print(f"[{index:02d}/{len(items):02d}] cached  {record['title']}")
                continue
        print(f"[{index:02d}/{len(items):02d}] export  {item['title']}")
        record = export_article(index, item, auth)
        state_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        records.append(record)
        time.sleep(0.15)

    records.sort(key=lambda x: x["index"])
    manifest = {
        "schema_version": 1,
        "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "album": album,
        "articles": records,
        "failed_assets": FAILED_ASSETS,
    }
    (ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    write_index(album, records)
    write_readme(album, records)
    write_checksums()
    print("[3/4] Wrote index, manifest, README, and checksums.")
    print(f"[4/4] Complete: {len(records)} articles, {len(list(ASSETS_DIR.iterdir()))} local assets, {len(FAILED_ASSETS)} failed assets.")
    return 0 if not FAILED_ASSETS else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted; completed articles remain resumable.", file=sys.stderr)
        raise SystemExit(130)
