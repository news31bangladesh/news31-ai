#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""News 31 trial: build ONE 30s 9:16 Reel (1080x1920) from footage.

Pipeline: footage clips (or the motion title card when no footage)
-> one base video of exactly the voiceover length (cap 30s) ->
one final encode that adds the News 31 logo (top-right), the
headline lower-third (slides in), the scrolling breaking-news
ticker (bottom) and the voiceover. NO photo anywhere in the video.

Writes reel.mp4, caption.txt (headline + direct blog URL +
question + hashtags) and meta.json (story, duration, footage
source credit, what was used). Exits non-zero when the Reel
cannot be built - the trial must fail loudly, not silently.
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

WIDTH, HEIGHT = 1080, 1920
MAX_DURATION = 30.0
TICKER_SPEED = 90
CAPTION_QUESTION = "আপনার মতামত কী? কমেন্টে জানান।"
CAPTION_HASHTAGS = "#News31 #BreakingNews"


def run(cmd, timeout=600):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError("command failed (%s): %s"
                           % (" ".join(cmd[:6]),
                              (r.stderr or "")[-400:]))
    return r


def media_duration(path):
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                            "format=duration", "-of",
                            "default=noprint_wrappers=1:nokey=1", path],
                           capture_output=True, text=True, timeout=60)
        return float((r.stdout or "0").strip() or 0)
    except Exception:
        return 0.0


def concat_clips(clip_paths, duration, out_path, work_dir):
    lst = os.path.join(work_dir, "concat_list.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for p in clip_paths:
            f.write("file '%s'\n" % p.replace("'", "'\\''"))
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
         "-i", lst, "-c", "copy", "-t", "%.3f" % duration, out_path])
    return out_path


def motion_card_video(card_png, duration, out_path):
    """Still card with a slow zoom - real motion, never a photo."""
    run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-framerate", "30",
         "-t", "%.3f" % duration, "-i", card_png,
         "-vf", ("zoompan=z='min(1+0.10*on/(30*%.1f),1.10)':"
                 "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:"
                 "s=%dx%d:fps=30" % (duration, WIDTH, HEIGHT)),
         "-c:v", "libx264", "-preset", "veryfast",
         "-pix_fmt", "yuv420p", "-r", "30", "-an", out_path])
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--story", required=True)
    ap.add_argument("--voice", required=True)
    ap.add_argument("--clips", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--logo", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    with open(args.story, encoding="utf-8") as f:
        story = json.load(f)
    with open(args.clips, encoding="utf-8") as f:
        footage = json.load(f)
    assets = {}
    assets_path = os.path.join(args.work, "assets.json")
    if os.path.exists(assets_path):
        with open(assets_path, encoding="utf-8") as f:
            assets = json.load(f)

    voice_dur = media_duration(args.voice)
    if voice_dur <= 0:
        print("[build] voice file is empty - NO VIDEO (hard rule)",
              file=sys.stderr)
        return 1
    duration = min(voice_dur, MAX_DURATION)
    print("[build] voice %.1fs -> Reel %.1fs" % (voice_dur, duration))

    os.makedirs(args.work, exist_ok=True)
    base = os.path.join(args.work, "base.mp4")
    clip_paths = footage.get("clips") or []
    used_footage = bool(clip_paths)
    if used_footage:
        print("[build] base video from %d footage clips" % len(clip_paths))
        concat_clips(clip_paths, duration, base, args.work)
    else:
        card = assets.get("card")
        if not card or not os.path.exists(card):
            print("[build] no footage AND no motion card - cannot build",
                  file=sys.stderr)
            return 1
        print("[build] no footage - motion title card fallback")
        motion_card_video(card, duration, base)
    if not os.path.exists(base) or os.path.getsize(base) < 5000:
        print("[build] base video failed", file=sys.stderr)
        return 1

    # ---- final encode: logo + lower-third + ticker + voiceover ----
    inputs = ["-i", base]
    filters = []
    prev = "[0:v]"
    idx = 1
    lower = assets.get("lower")
    if lower and os.path.exists(lower):
        inputs += ["-i", lower]
        filters.append("[%d:v]format=rgba[low]" % idx)
        filters.append("%s[low]overlay=x='(W-w)/2':"
                       "y='if(lt(t,0.8),1500+140*(0.8-t)/0.8,1500)'[ov%d]"
                       % (prev, idx))
        prev = "[ov%d]" % idx
        idx += 1
    ticker = assets.get("ticker")
    if ticker and os.path.exists(ticker):
        inputs += ["-i", ticker]
        filters.append("%s[%d:v]overlay=x='W-mod(t*%d,W+w)':y=H-90[ov%d]"
                       % (prev, idx, TICKER_SPEED, idx))
        prev = "[ov%d]" % idx
        idx += 1
    if args.logo and os.path.exists(args.logo):
        inputs += ["-i", args.logo]
        filters.append("[%d:v]scale=150:-1[lg]" % idx)
        filters.append("%s[lg]overlay=x=W-w-40:y=220[ov%d]"
                       % (prev, idx))
        prev = "[ov%d]" % idx
        idx += 1
    inputs += ["-i", args.voice]
    cmd = ["ffmpeg", "-y", "-v", "error"] + inputs
    if filters:
        cmd += ["-filter_complex", ";".join(filters),
                "-map", prev, "-map", "%d:a" % idx]
    else:
        cmd += ["-map", "0:v", "-map", "%d:a" % idx]
    cmd += ["-t", "%.3f" % duration,
            "-c:v", "libx264", "-preset", "veryfast",
            "-pix_fmt", "yuv420p", "-r", "30",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart", args.out]
    run(cmd, timeout=900)
    if not os.path.exists(args.out) or os.path.getsize(args.out) < 5000:
        print("[build] final encode produced no video", file=sys.stderr)
        return 1
    size_mb = os.path.getsize(args.out) / 1e6
    print("[build] reel.mp4: %.1fs, %.2f MB" % (duration, size_mb))

    caption = "%s\n%s\n%s\n%s" % (story["title"], story["url"],
                                   CAPTION_QUESTION, CAPTION_HASHTAGS)
    caption_path = os.path.join(os.path.dirname(os.path.abspath(args.out)),
                                "caption.txt")
    with open(caption_path, "w", encoding="utf-8") as f:
        f.write(caption)
    meta = {"title": story["title"], "url": story["url"],
            "published": story.get("published", ""),
            "duration_seconds": round(duration, 2),
            "voice_seconds": round(voice_dur, 2),
            "size_mb": round(size_mb, 2),
            "footage": used_footage,
            "footage_source": footage.get("source"),
            "assets_used": {k: bool(v) for k, v in assets.items()},
            "created_at_utc": datetime.now(timezone.utc).isoformat()}
    meta_path = os.path.join(os.path.dirname(os.path.abspath(args.out)),
                             "meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print("[build] caption.txt + meta.json written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
