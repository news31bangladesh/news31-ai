#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""News 31 trial: fetch the newest story from the public Blogger feed.

No auth needed - the blog feed is public. With --url, that exact
blog post is used instead (handy for re-running the trial on one
story). Writes story.json: {title, url, published, age_hours,
body_text}. Exits non-zero only when the feed cannot be read at all.
"""
import argparse
import html
import json
import re
import sys
from datetime import datetime, timezone

import requests

FEED_URL = ("https://news31bangladesh.blogspot.com/feeds/posts/"
            "default?alt=json&max-results=5")


def clean_text(raw):
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--url", default="")
    args = ap.parse_args()

    r = requests.get(FEED_URL, timeout=30)
    r.raise_for_status()
    entries = r.json().get("feed", {}).get("entry", [])
    if not entries:
        print("[fetch] blog feed is empty", file=sys.stderr)
        return 1

    picked = None
    if args.url:
        for e in entries:
            for link in e.get("link", []):
                if link.get("rel") == "alternate" and \
                        link.get("href", "").rstrip("/") == args.url.rstrip("/"):
                    picked = e
                    break
            if picked:
                break
        if not picked:
            print("[fetch] URL not in the 5 newest posts: %s"
                  % args.url, file=sys.stderr)
            return 1
    else:
        picked = entries[0]

    title = html.unescape(
        picked.get("title", {}).get("$t", "")).strip()
    url = ""
    for link in picked.get("link", []):
        if link.get("rel") == "alternate":
            url = link.get("href", "")
    published = picked.get("published", {}).get("$t", "")
    age_hours = None
    try:
        dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
        age_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
    except Exception:
        pass
    body = clean_text(picked.get("content", {}).get("$t", ""))

    story = {"title": title, "url": url, "published": published,
             "age_hours": age_hours, "body_text": body[:2000]}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(story, f, ensure_ascii=False, indent=2)
    print("[fetch] %s" % title)
    print("[fetch] %s (age %.1fh)"
          % (url, age_hours if age_hours is not None else -1))
    if age_hours is not None and age_hours > 4:
        print("[fetch] WARNING: newest post is %.1fh old - the trial "
              "still builds it, but a live Reel normally wants <4h."
              % age_hours)
    return 0


if __name__ == "__main__":
    sys.exit(main())
