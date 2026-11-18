#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""News 31 trial: collect ORIGINAL video footage for one story.

Same rules as the laptop AI (v8.7 + v8.7.1 field-footage fix):
  * yt-dlp search by headline keywords; pick the first short report
    (20s-12min, not live); download at most 720p. The search tries
    YouTube player clients in order (android, web, plain) - YouTube
    often blocks plain searches from datacenter IPs, and the android
    client usually gets through. Every attempt is logged, with the
    stderr tail when it fails, so a silent "no footage" is
    diagnosable from the run log. A search that finds nothing is
    retried once with a shorter query (first 4 words).
  * Skip the ANCHOR parts - the field report is in the middle:
    videos >= 60s lose the first 15s + last 10s; shorter videos lose
    the first 25% + last 15%. Clips are planned middle-first.
  * Cut the source's bottom 12% bar BEFORE the aspect crop, crop to
    9:16 with a slight zoom (cuts edge bugs), scale 1080x1920.
  * DROP the source audio entirely (-an). Clips are 4-12s each.
  * Never more than a few seconds from any one spot (copyright:
    short clips, transformed, own voiceover, source credited in
    meta.json).

Writes clips.json: {"clips": [...], "source": {...} | null}.
Never raises / never exits non-zero for "no footage" - the caller
falls back to the News 31 motion title card instead. Exit 1 only
on a usage error (bad arguments, missing voice file).
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys

MAX_CLIP = 12
MIN_CLIP = 4
FORMAT_HEIGHT = 720
SEARCH_RESULTS = 5
MAX_VIDEO_SECONDS = 720
MIN_VIDEO_SECONDS = 20
PLAYER_CLIENTS = ["android", "web", None]  # None = plain, no extractor-args
ANCHOR_SKIP_HEAD = 15      # >= 60s videos: skip first 15s (anchor intro)
ANCHOR_SKIP_TAIL = 10      # >= 60s videos: skip last 10s (anchor outro)
SHORT_SKIP_HEAD_FRAC = 0.25
SHORT_SKIP_TAIL_FRAC = 0.15
BOTTOM_BAR_CUT = 0.12      # cut the source's own bottom bar (12%)
WIDTH, HEIGHT = 1080, 1920


def log(msg):
    print("[footage] %s" % msg, flush=True)


def find_ytdlp():
    exe = shutil.which("yt-dlp")
    if exe:
        return [exe]
    try:
        import yt_dlp  # noqa: F401
        return [sys.executable, "-m", "yt_dlp"]
    except Exception:
        return None


def media_duration(path):
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                            "format=duration", "-of",
                            "default=noprint_wrappers=1:nokey=1", path],
                           capture_output=True, text=True, timeout=60)
        return float((r.stdout or "0").strip() or 0)
    except Exception:
        return 0.0


def search_query(title):
    cleaned = re.sub(r"[।!?\"'(),:;|।\-–—/]", " ", title or "")
    words = [w for w in cleaned.split() if len(w) > 1]
    return " ".join(words[:8]) or title


def short_query(query):
    """First 4 words of a search query - a broader retry when the
    full query finds nothing."""
    return " ".join((query or "").split()[:4])


def _stderr_tail(text, max_lines=3):
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    return " | ".join(lines[-max_lines:])


def _parse_search_json(stdout):
    out = []
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            info = json.loads(line)
        except Exception:
            continue
        if info.get("is_live"):
            continue
        vid = info.get("id") or ""
        out.append({"id": vid,
                    "title": info.get("title") or "",
                    "url": info.get("webpage_url") or
                    "https://www.youtube.com/watch?v=%s" % vid,
                    "duration": info.get("duration") or 0,
                    "channel": info.get("channel") or
                    info.get("uploader") or ""})
    return out


def search_youtube(query, ytdlp):
    """Search YouTube, trying player clients in order (android, web,
    plain). Returns (results, client) - client is the name that
    worked, or None when nothing worked. Every attempt is logged,
    with the stderr tail when it finds nothing, so the next failure
    is diagnosable from the run log instead of silent."""
    for client in PLAYER_CLIENTS:
        label = client or "plain"
        cmd = list(ytdlp) + ["--dump-json", "--no-playlist",
                             "--no-warnings"]
        if client:
            cmd += ["--extractor-args",
                    "youtube:player_client=%s" % client]
        cmd += ["ytsearch%d:%s" % (SEARCH_RESULTS, query)]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=120)
        except Exception as e:
            log("search [%s] error: %s" % (label, e))
            continue
        results = _parse_search_json(r.stdout)
        log("search [%s]: %d result(s)" % (label, len(results)))
        if results:
            return results, client
        err = _stderr_tail(r.stderr)
        if err:
            log("search [%s] stderr: %s" % (label, err))
    return [], None


def download_footage(video_url, out_path, ytdlp, client=None):
    fmt = ("bestvideo[height<=%d][ext=mp4]/best[height<=%d][ext=mp4]/best"
           % (FORMAT_HEIGHT, FORMAT_HEIGHT))
    cmd = list(ytdlp)
    if client:
        cmd += ["--extractor-args", "youtube:player_client=%s" % client]
    cmd += ["-f", fmt, "--merge-output-format", "mp4",
            "--no-playlist", "--no-warnings", "--retries", "2",
            "-o", out_path, video_url]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except Exception as e:
        log("download error: %s" % e)
        return False
    ok = (r.returncode == 0 and os.path.exists(out_path)
          and os.path.getsize(out_path) > 10000)
    if not ok:
        err = _stderr_tail(r.stderr)
        log("download failed (rc=%s)%s"
            % (r.returncode, (" - " + err) if err else ""))
    return ok


def usable_range(src_duration):
    """v8.7.1: the field-report middle of the video (anchor intro /
    outro removed). Returns (lo, hi) in seconds."""
    if src_duration >= 60:
        return float(ANCHOR_SKIP_HEAD), src_duration - ANCHOR_SKIP_TAIL
    return (src_duration * SHORT_SKIP_HEAD_FRAC,
            src_duration * (1.0 - SHORT_SKIP_TAIL_FRAC))


def plan_clips(src_duration, need_seconds):
    """(start, dur) clips covering >= need_seconds, planned
    middle-first, then outward - never inside the anchor zones.
    Returns [] when the usable part is too short."""
    lo, hi = usable_range(src_duration)
    avail = hi - lo
    if avail < MIN_CLIP:
        return []
    n = max(1, int(-(-need_seconds // MAX_CLIP)))
    each = need_seconds / float(n)
    if each < MIN_CLIP:
        each = float(MIN_CLIP)
        n = max(1, int(-(-need_seconds // MIN_CLIP)))
    span = avail - each
    if span <= 0:
        starts = [float(lo)]
    else:
        per_pass = max(1, int(avail // each))
        if per_pass == 1:
            starts = [float(lo)]
        else:
            starts = [lo + span * k / float(per_pass - 1)
                      for k in range(per_pass)]
    # Middle-first ordering: closest to the centre first.
    mid = (lo + hi) / 2.0
    starts.sort(key=lambda s: abs((s + each / 2.0) - mid))
    clips = []
    total = 0.0
    i = 0
    while total < need_seconds and i < 500:
        s = starts[i % len(starts)]
        d = min(each, need_seconds - total)
        if d <= 0:
            break
        clips.append((round(s, 3), round(d, 3)))
        total += d
        i += 1
    if clips:
        rounded_total = sum(d for _s, d in clips)
        if rounded_total < need_seconds:
            s, d = clips[-1]
            clips[-1] = (s, round(d + (need_seconds - rounded_total), 3))
    return clips


def crop_filter(width, height, zoom):
    """Bottom 12% cut FIRST, then crop to the target aspect with a
    slight zoom (cuts edge watermarks/bugs), then scale."""
    aspect = width / float(height)
    return ("crop=iw:ih*%f:0:0,"
            "crop='min(iw,ih*%f)/%f:min(ih,iw/%f)/%f',"
            "scale=%d:%d" % (1.0 - BOTTOM_BAR_CUT,
                             aspect, zoom, aspect, zoom, width, height))


def clean_and_cut(src, start, dur, out_path, zoom):
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-ss", "%.3f" % start, "-t", "%.3f" % dur, "-i", src,
           "-vf", crop_filter(WIDTH, HEIGHT, zoom),
           "-an", "-c:v", "libx264", "-preset", "veryfast",
           "-pix_fmt", "yuv420p", "-r", "30", out_path]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except Exception:
        return False
    return (r.returncode == 0 and os.path.exists(out_path)
            and os.path.getsize(out_path) > 1000)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--story", required=True)
    ap.add_argument("--voice", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    result = {"clips": [], "source": None}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    with open(args.story, encoding="utf-8") as f:
        story = json.load(f)
    need = media_duration(args.voice)
    if need <= 0:
        print("[footage] voice file has no duration - skipping footage",
              file=sys.stderr)
        return 0
    need = min(need, 30.0)
    log("need %.1fs of footage for: %s" % (need, story["title"][:60]))

    ytdlp = find_ytdlp()
    if not ytdlp:
        log("yt-dlp is not installed - motion card fallback")
        return 0
    query = search_query(story["title"])
    if not query:
        log("empty search query - motion card fallback")
        return 0
    results, client = search_youtube(query, ytdlp)
    if not results:
        short = short_query(query)
        if short and short != query:
            log("no results - retrying with shorter query: %s" % short)
            results, client = search_youtube(short, ytdlp)
    pick = None
    for cand in results:
        dur = cand.get("duration") or 0
        if MIN_VIDEO_SECONDS <= dur <= MAX_VIDEO_SECONDS:
            pick = cand
            break
    if pick is None:
        log("no usable footage for this headline - motion card fallback")
        return 0

    os.makedirs(args.work, exist_ok=True)
    src = os.path.join(args.work, "footage_%s.mp4" % pick["id"])
    if not (os.path.exists(src) and os.path.getsize(src) > 10000
            and media_duration(src) > 0):
        if not download_footage(pick["url"], src, ytdlp, client):
            log("download failed - motion card fallback")
            return 0
    src_dur = media_duration(src)
    if src_dur < MIN_VIDEO_SECONDS:
        log("downloaded video too short - motion card fallback")
        return 0
    plan = plan_clips(src_dur, need)
    if not plan:
        log("no usable field segment - motion card fallback")
        return 0
    clips = []
    for ci, (start, dur) in enumerate(plan):
        out = os.path.join(args.work, "clip_%s_%02d.mp4"
                           % (pick["id"][:12], ci))
        if os.path.exists(out) and os.path.getsize(out) > 5000:
            clips.append(out)
            continue
        zoom = 1.04 if (ci % 2 == 0) else 1.10
        if clean_and_cut(src, start, dur, out, zoom):
            clips.append(out)
    if not clips:
        log("all clip cuts failed - motion card fallback")
        return 0
    result = {"clips": clips,
              "source": {"channel": pick.get("channel", ""),
                         "title": pick.get("title", ""),
                         "url": pick.get("url", "")}}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    log("footage: %s - %s (%.0fs source, %d clips)"
        % (result["source"]["channel"], result["source"]["title"][:50],
           src_dur, len(clips)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
