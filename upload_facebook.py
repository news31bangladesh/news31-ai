#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""News 31 trial: publish the Reel on the News 31 Facebook Page.

Same 3-phase Graph API upload as the laptop publisher
(start -> transfer -> finish, PUBLISHED). The token comes ONLY
from the FB_PAGE_TOKEN environment variable (a GitHub Actions
secret) - it is never printed, never written to any file.

When FB_PAGE_TOKEN is missing or empty the script prints SKIP and
exits 0: the trial still succeeds (the video is in the workflow
artifact) - the upload is optional. Exit 1 only when a token WAS
given but the upload itself failed.

Page safety: on a "temporarily blocked / going too fast / rate
limit" answer from Facebook, exit 2 (blocked - never force it).
"""
import argparse
import os
import sys

import requests

GRAPH = "https://graph.facebook.com/v21.0"
PAGE_ID = "548123798376765"  # News 31 Page (public id, not a secret)
BLOCK_CODES = {4, 17, 32, 368, 613, 80004}
BLOCK_WORDS = ("temporarily blocked", "going too fast", "rate limit",
               "too many calls", "action blocked")


def fail(msg, code=1):
    print("[facebook] FAILED: %s" % msg, file=sys.stderr)
    return code


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--caption", required=True)
    args = ap.parse_args()

    token = os.environ.get("FB_PAGE_TOKEN", "").strip()
    if not token:
        print("[facebook] SKIP - no FB_PAGE_TOKEN secret set. "
              "The Reel is still in the workflow artifact.")
        return 0
    if not os.path.exists(args.video):
        return fail("video file not found: %s" % args.video)
    with open(args.caption, encoding="utf-8") as f:
        caption = f.read().strip()

    base = "%s/%s/video_reels" % (GRAPH, PAGE_ID)
    # Phase 1: start.
    try:
        r = requests.post(base, data={"upload_phase": "start",
                                      "access_token": token}, timeout=30)
        data = r.json()
    except Exception as e:
        return fail("start request failed: %s" % e)
    if r.status_code != 200 or "video_id" not in data:
        err = (data or {}).get("error", {})
        msg = err.get("message", str(data))
        if err.get("code") in BLOCK_CODES or \
                any(w in msg.lower() for w in BLOCK_WORDS):
            print("[facebook] BLOCKED by Facebook (%s) - not forced"
                  % msg, file=sys.stderr)
            return 2
        return fail("start failed (HTTP %s): %s" % (r.status_code, msg))
    video_id, upload_url = data["video_id"], data["upload_url"]
    print("[facebook] upload started, video id %s" % video_id)

    # Phase 2: transfer (headers MUST be offset + file_size).
    with open(args.video, "rb") as f:
        video_bytes = f.read()
    try:
        r = requests.post(upload_url,
                          headers={"Authorization": "OAuth " + token,
                                   "offset": "0",
                                   "file_size": str(len(video_bytes))},
                          data=video_bytes, timeout=300)
        data = r.json()
    except Exception as e:
        return fail("transfer failed: %s" % e)
    if r.status_code != 200 or not data.get("success"):
        err = (data or {}).get("error", {})
        msg = err.get("message", str(data))
        if err.get("code") in BLOCK_CODES or \
                any(w in msg.lower() for w in BLOCK_WORDS):
            print("[facebook] BLOCKED by Facebook (%s) - not forced"
                  % msg, file=sys.stderr)
            return 2
        return fail("transfer failed (HTTP %s): %s" % (r.status_code, msg))
    print("[facebook] bytes uploaded (%.2f MB)" % (len(video_bytes) / 1e6))

    # Phase 3: finish + publish with the caption.
    try:
        r = requests.post(base, data={"upload_phase": "finish",
                                      "video_id": video_id,
                                      "video_state": "PUBLISHED",
                                      "description": caption,
                                      "access_token": token}, timeout=60)
        data = r.json()
    except Exception as e:
        return fail("finish failed: %s" % e)
    if r.status_code != 200 or not data.get("success", True):
        err = (data or {}).get("error", {})
        return fail("finish failed (HTTP %s): %s"
                    % (r.status_code, err.get("message", str(data))))
    print("[facebook] REEL PUBLISHED, video id %s" % video_id)
    print("[facebook] https://www.facebook.com/news31.me")
    return 0


if __name__ == "__main__":
    sys.exit(main())
