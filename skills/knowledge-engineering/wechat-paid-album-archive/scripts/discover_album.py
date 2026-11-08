#!/usr/bin/env python3
"""Discover public WeChat album identifiers without reading authentication data."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup


UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 Chrome/124 Safari/537.36"
)


def public_url(value: str) -> str:
    parts = urlsplit(html.unescape(value))
    allowed = {"__biz", "mid", "idx", "sn", "chksm"}
    query = [(key, item) for key, item in parse_qsl(parts.query) if key in allowed]
    return urlunsplit((parts.scheme or "https", parts.netloc, parts.path, urlencode(query), ""))


def first_match(text: str, patterns: list[str]) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return html.unescape(unquote(match.group(1))).strip()
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read public album ID and __biz metadata from a WeChat article or album URL."
    )
    parser.add_argument("url", help="Public mp.weixin.qq.com article or album URL")
    args = parser.parse_args()

    request = Request(args.url, headers={"User-Agent": UA, "Accept-Encoding": "identity"})
    with urlopen(request, timeout=45) as response:
        final_url = response.geturl()
        page = response.read().decode("utf-8", "replace")
    decoded = html.unescape(unquote(page))
    decoded = re.sub(r"\\x([0-9a-fA-F]{2})", lambda match: chr(int(match.group(1), 16)), decoded)
    decoded = html.unescape(decoded)
    final_query = dict(parse_qsl(urlsplit(final_url).query, keep_blank_values=True))

    album_id = final_query.get("album_id", "") or first_match(
        decoded,
        [
            r"cur_album_id\s*[:=]\s*['\"](\d+)",
            r"album_id\s*[:=]\s*['\"](\d+)",
            r"[?&]album_id=(\d+)",
        ],
    )
    biz = final_query.get("__biz", "") or first_match(
        decoded,
        [
            r"[?&]__biz=([A-Za-z0-9+/]{8,}={0,2})",
            r"\b(?:biz|__biz)\s*[:=]\s*['\"]([A-Za-z0-9+/]{8,}={0,2})",
        ],
    )

    soup = BeautifulSoup(page, "html.parser")
    title_meta = soup.select_one('meta[property="og:title"]')
    title = title_meta.get("content", "").strip() if title_meta else ""
    result = {
        "title": title,
        "public_url": public_url(final_url),
        "album_id": album_id,
        "biz": biz,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not album_id or not biz:
        print(
            "Could not discover both identifiers. Open the collection page normally and pass its "
            "mp/appmsgalbum URL, which contains album_id and __biz.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
