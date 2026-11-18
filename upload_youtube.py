#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""News 31 trial: upload the same Reel to YouTube as a Short.

Auth: the Google OAuth client (YOUTUBE_CLIENT_ID +
YOUTUBE_CLIENT_SECRET) plus the refresh token
(YOUTUBE_REFRESH_TOKEN) - all three from environment variables
(GitHub Actions secrets). The refresh token is exchanged for a
short-lived access token; no token value is ever printed or
written to a file.

When any of the three is missing the script prints SKIP and exits
0: the trial still succeeds (the video is in the workflow
artifact) - the upload is optional. Exit 1 only when credentials
WERE given but the upload itself failed.
"""
import argparse
import json
import os
import sys

import requests

TOKEN_URL = "https://oauth2.googleapis.com/token"
TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
UPLOAD_SESSION_URL = ("https://www.googleapis.com/upload/youtube/v3/"
                      "videos?uploadType=resumable&part=snippet,status")
YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"


def fail(msg):
    print("[youtube] FAILED: %s" % msg, file=sys.stderr)
    return 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--url", default="")
    ap.add_argument("--caption", default="")
    args = ap.parse_args()

    client_id = os.environ.get("YOUTUBE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET", "").strip()
    refresh = os.environ.get("YOUTUBE_REFRESH_TOKEN", "").strip()
    missing = [n for n, v in
               (("YOUTUBE_CLIENT_ID", client_id),
                ("YOUTUBE_CLIENT_SECRET", client_secret),
                ("YOUTUBE_REFRESH_TOKEN", refresh)) if not v]
    if missing:
        print("[youtube] SKIP - missing secret(s): %s. The Reel is "
              "still in the workflow artifact." % ", ".join(missing))
        return 0
    if not os.path.exists(args.video):
        return fail("video file not found: %s" % args.video)

    # Refresh token -> access token.
    try:
        r = requests.post(TOKEN_URL, data={
            "grant_type": "refresh_token", "client_id": client_id,
            "client_secret": client_secret, "refresh_token": refresh},
            timeout=30)
        token = r.json().get("access_token", "")
    except Exception as e:
        return fail("token exchange failed: %s" % e)
    if not token:
        return fail("token exchange gave no access token "
                    "(refresh token may be expired - re-authorize).")
    try:
        r = requests.get(TOKENINFO_URL, params={"access_token": token},
                         timeout=20)
        scopes = set(r.json().get("scope", "").split())
        if scopes and YOUTUBE_UPLOAD_SCOPE not in scopes:
            return fail("token has no youtube.upload scope - "
                        "re-authorize with the YouTube scope.")
    except Exception:
        pass  # scope check is best-effort; the upload will tell us

    title = args.title.strip()
    if len(title) > 100:
        title = title[:97].rsplit(" ", 1)[0] + "..."
    description = args.caption.strip() or "%s\n%s" % (title, args.url)
    size = os.path.getsize(args.video)
    metadata = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": ["News31", "Bangladesh News", "Breaking News"],
            "categoryId": "25",  # News & Politics
        },
        "status": {"privacyStatus": "public",
                   "selfDeclaredMadeForKids": False},
    }
    try:
        r = requests.post(UPLOAD_SESSION_URL,
                          headers={"Authorization": "Bearer " + token,
                                   "Content-Type":
                                   "application/json; charset=UTF-8",
                                   "X-Upload-Content-Type": "video/mp4",
                                   "X-Upload-Content-Length": str(size)},
                          json=metadata, timeout=60)
    except Exception as e:
        return fail("upload session failed: %s" % e)
    if r.status_code != 200:
        try:
            reason = (r.json().get("error", {}).get("errors", [{}])[0]
                      .get("reason", ""))
        except Exception:
            reason = ""
        if reason == "accessNotConfigured":
            return fail("YouTube Data API is not enabled in the Google "
                        "project - enable 'YouTube Data API v3'.")
        return fail("upload session failed (HTTP %s)." % r.status_code)
    session_url = r.headers.get("Location", "")
    if not session_url:
        return fail("Google gave no upload URL.")
    try:
        with open(args.video, "rb") as f:
            data = f.read()
        r = requests.put(session_url,
                         headers={"Content-Type": "video/mp4",
                                  "Content-Length": str(len(data))},
                         data=data, timeout=300)
    except Exception as e:
        return fail("video bytes upload failed: %s" % e)
    if r.status_code not in (200, 201):
        return fail("video upload failed (HTTP %s)." % r.status_code)
    video_id = r.json().get("id", "")
    if not video_id:
        return fail("Google gave no video id.")
    print("[youtube] SHORT UPLOADED: "
          "https://www.youtube.com/shorts/%s" % video_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
