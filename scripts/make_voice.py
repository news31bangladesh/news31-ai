#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""News 31 trial: Bangla voiceover with edge-tts (free, no key).

Reads story.json, speaks ONLY the headline + the website line
(the same words the laptop Reels speak), and saves voice.mp3.

Voice chain (same order as the laptop v8.5 fallback): Pradeep ->
Nabanita -> Tanishaa -> Bashkar. One voice failing never stops the
Reel - the next one is tried. If ALL voices fail, this script exits
non-zero: the hard rule is NO voice -> NO video, ever.
"""
import argparse
import asyncio
import json
import os
import sys
import time

VOICES = ["bn-BD-PradeepNeural", "bn-BD-NabanitaNeural",
          "bn-BD-TanishaaNeural", "bn-BD-BashkarNeural"]
WEBSITE_LINE = ("বিস্তারিত নিউজ পড়তে অথবা জানতে আমাদের ওয়েবসাইট "
                "ভিজিট করুন, ক্যাপশনে ওয়েবসাইট লিংক দেওয়া আছে")
TRIES_PER_VOICE = 2
TRY_TIMEOUT = 90


def narration_text(story):
    return "%s। %s" % (story["title"].strip(), WEBSITE_LINE)


def try_voice(text, voice, out_path):
    """One edge-tts attempt. Returns True on a real audio file."""
    import edge_tts

    async def _run():
        await asyncio.wait_for(
            edge_tts.Communicate(text, voice, rate="+0%").save(out_path),
            timeout=TRY_TIMEOUT)

    try:
        asyncio.run(_run())
    except Exception as e:
        print("[voice] %s failed: %s" % (voice, e))
        return False
    if os.path.exists(out_path) and os.path.getsize(out_path) > 500:
        return True
    print("[voice] %s produced an empty file" % voice)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--story", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    with open(args.story, encoding="utf-8") as f:
        story = json.load(f)
    text = narration_text(story)
    print("[voice] text (%d chars): %s" % (len(text), text[:120]))

    for voice in VOICES:
        for attempt in range(TRIES_PER_VOICE):
            if try_voice(text, voice, args.out):
                print("[voice] OK with %s (try %d)"
                      % (voice, attempt + 1))
                return 0
            if attempt + 1 < TRIES_PER_VOICE:
                time.sleep(5)
        print("[voice] %s gave up - trying next voice" % voice)

    print("[voice] ALL VOICES FAILED - no video will be built",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
