#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""News 31 trial: render the Bangla overlay PNGs with Pillow.

Outputs in the work dir:
  lower.png  - headline on a dark band (lower-third, ~y 1500)
  ticker.png - red scrolling strip, headline repeated x3
  card.png   - 1080x1920 motion title card (logo + headline),
               used ONLY when no footage could be downloaded.

Needs a Bangla font on the machine (the workflow installs
fonts-bengali). Pillow's wheels ship with libraqm, so conjuncts
shape correctly. Never fails the job: when a font cannot be found
at all, the text PNGs are skipped and the Reel is built without
that overlay.
"""
import argparse
import glob
import json
import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

RED = (192, 0, 0, 255)
GOLD = (212, 175, 55, 255)
WHITE = (255, 255, 255, 255)
DARK_BAND = (0, 0, 0, 190)

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/lohit-bengali/Lohit-Bengali.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansBengali-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSerifBengali-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansBengali-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSerifBengali-Regular.ttf",
]


def find_font():
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    for pat in ("/usr/share/fonts/**/NotoSansBengali*.ttf",
                "/usr/share/fonts/**/Lohit-Bengali*.ttf",
                "/usr/share/fonts/**/NotoSerifBengali*.ttf"):
        hits = sorted(glob.glob(pat, recursive=True))
        if hits:
            return hits[0]
    try:
        r = subprocess.run(["fc-match", "-f", "%{file}", ":lang=bn"],
                           capture_output=True, text=True, timeout=20)
        p = (r.stdout or "").strip()
        if p and os.path.exists(p):
            return p
    except Exception:
        pass
    hits = sorted(glob.glob("/usr/share/fonts/**/*.ttf", recursive=True))
    return hits[0] if hits else None


def find_lat_font():
    """Latin font for the website line - Bengali fonts ship without
    Latin glyphs (they render as tofu boxes), so this must be a
    Latin font (DejaVu ships with every Ubuntu runner)."""
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"):
        if os.path.exists(p):
            return p
    hits = sorted(glob.glob("/usr/share/fonts/**/DejaVuSans*.ttf",
                            recursive=True))
    return hits[0] if hits else FONT_PATH


def font(path, size):
    return ImageFont.truetype(path, size)


def wrap_lines(draw, text, fnt, max_w):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        cand = (cur + " " + w).strip()
        if draw.textlength(cand, font=fnt) <= max_w or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def render_text_png(text, size, color, max_w, out_path, align="center"):
    """One transparent PNG with the text wrapped to max_w."""
    fnt = font(FONT_PATH, size)
    tmp = Image.new("RGBA", (10, 10))
    d = ImageDraw.Draw(tmp)
    lines = wrap_lines(d, text, fnt, max_w)
    line_h = int(size * 1.35)
    w = max(int(d.textlength(ln, font=fnt)) for ln in lines) + 8
    h = line_h * len(lines) + 8
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    y = 4
    for ln in lines:
        if align == "center":
            x = (w - d.textlength(ln, font=fnt)) / 2
        else:
            x = 4
        d.text((x, y), ln, font=fnt, fill=color)
        y += line_h
    img.save(out_path, "PNG")
    return out_path


def make_lower(headline, work_dir):
    """Headline on a dark translucent band (lower-third)."""
    fnt = font(FONT_PATH, 64)
    tmp = Image.new("RGBA", (10, 10))
    d = ImageDraw.Draw(tmp)
    lines = wrap_lines(d, headline, fnt, 920)[:3]
    line_h = int(64 * 1.35)
    text_h = line_h * len(lines)
    band_w, band_h = 1000, text_h + 56
    band = Image.new("RGBA", (band_w, band_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(band)
    d.rectangle([0, 0, band_w, band_h], fill=DARK_BAND)
    d.rectangle([0, 0, band_w, 6], fill=RED)
    y = 28
    for ln in lines:
        x = (band_w - d.textlength(ln, font=fnt)) / 2
        d.text((x, y), ln, font=fnt, fill=WHITE)
        y += line_h
    out = os.path.join(work_dir, "lower.png")
    band.save(out, "PNG")
    return out


def make_ticker(headline, work_dir):
    """Red scrolling strip - the headline repeated so the strip is
    wide enough to keep scrolling for the whole 30s Reel."""
    text = "  •  ".join([headline] * 3)
    tim = render_text_png(text, 44, WHITE, 20000,
                          os.path.join(work_dir, "ticker_text.png"),
                          align="left")
    tim_img = Image.open(tim)
    if tim_img.height > 80:
        return None
    strip = Image.new("RGBA", (tim_img.width + 120, 90), (0, 0, 0, 0))
    d = ImageDraw.Draw(strip)
    d.rectangle([0, 0, strip.width, 90], fill=RED)
    d.rectangle([0, 0, strip.width, 4], fill=GOLD)
    strip.paste(tim_img, (60, (90 - tim_img.height) // 2), tim_img)
    out = os.path.join(work_dir, "ticker.png")
    strip.save(out, "PNG")
    try:
        os.remove(tim)
    except Exception:
        pass
    return out


def make_card(headline, logo_path, work_dir):
    """1080x1920 motion title card: red/navy background, News 31
    logo, headline, website line. Only shown when no footage
    exists - never a photo."""
    W, H = 1080, 1920
    img = Image.new("RGB", (W, H), (10, 31, 68))
    d = ImageDraw.Draw(img)
    d.polygon([(0, 0), (W, 0), (0, H)], fill=(139, 0, 0))
    d.polygon([(0, 0), (W, 0), (W, int(H * 0.42))], fill=(165, 5, 5))
    if logo_path and os.path.exists(logo_path):
        logo = Image.open(logo_path).convert("RGB")
        logo = logo.resize((380, 380), Image.LANCZOS)
        img.paste(logo, ((W - 380) // 2, 380))
    fnt = font(FONT_PATH, 72)
    tmp = ImageDraw.Draw(img)
    lines = wrap_lines(tmp, headline, fnt, 920)[:4]
    line_h = int(72 * 1.4)
    y = 900
    d.rectangle([140, y - 30, W - 140, y - 24], fill=GOLD)
    for ln in lines:
        x = (W - tmp.textlength(ln, font=fnt)) / 2
        d.text((x, y), ln, font=fnt, fill=WHITE)
        y += line_h
    small = font(find_lat_font(), 36)
    site = "news31bangladesh.blogspot.com"
    d.text(((W - tmp.textlength(site, font=small)) / 2, 1700),
           site, font=small, fill=(255, 255, 255, 220))
    out = os.path.join(work_dir, "card.png")
    img.save(out, "PNG")
    return out


FONT_PATH = None


def main():
    global FONT_PATH
    ap = argparse.ArgumentParser()
    ap.add_argument("--story", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--logo", default="")
    args = ap.parse_args()

    with open(args.story, encoding="utf-8") as f:
        story = json.load(f)
    headline = (story.get("title") or "").strip()
    os.makedirs(args.work, exist_ok=True)

    FONT_PATH = find_font()
    made = {}
    if not FONT_PATH:
        print("[assets] no Bangla font found - overlays skipped",
              file=sys.stderr)
    else:
        print("[assets] font: %s" % FONT_PATH)
        try:
            made["lower"] = make_lower(headline, args.work)
        except Exception as e:
            print("[assets] lower-third failed: %s" % e)
        try:
            made["ticker"] = make_ticker(headline, args.work)
        except Exception as e:
            print("[assets] ticker failed: %s" % e)
    try:
        made["card"] = make_card(headline, args.logo, args.work)
    except Exception as e:
        print("[assets] motion card failed: %s" % e, file=sys.stderr)
        return 1
    print("[assets] made: %s" % json.dumps(made, ensure_ascii=False))
    with open(os.path.join(args.work, "assets.json"), "w",
              encoding="utf-8") as f:
        json.dump(made, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
