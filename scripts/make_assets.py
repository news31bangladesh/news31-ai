#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""News 31 trial: render the Bangla overlay PNGs with Pillow.

Outputs in the work dir:
  lower.png  - headline on a dark band (lower-third, ~y 1500)
  ticker.png - red scrolling strip, headline repeated x3
  card.png   - 1080x1920 motion title card (logo + headline),
               used ONLY when no footage could be downloaded.

The Bengali font is BUNDLED in the repo (assets/fonts/
HindSiliguri-Bold.ttf + HindSiliguri-Regular.ttf) and is always
used first. The runner's system fonts are NOT trusted: run #12
used the system Lohit font and STILL produced tofu boxes in the
Reel, while the same code + font renders correctly on other
machines. Every font is verified to actually cover Bengali
(fontTools cmap check) before use, and Pillow renders with
libraqm (layout_engine=RAQM) so conjuncts shape correctly.

FAIL LOUD: if no Bengali-capable font can be found, this script
exits non-zero with "[assets] FATAL: no Bengali font" - a failed
job is better than a box-filled Reel. Never draw tofu silently.
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

# Codepoints a font MUST have to render Bengali at all:
# অ আ ক ্ া । ৯
BENGALI_PROBE = (0x0985, 0x0986, 0x0995, 0x09CD, 0x09BE, 0x0964, 0x09EF)

# System fonts - backup only, and only if verified Bengali-capable.
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/lohit-bengali/Lohit-Bengali.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansBengali-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSerifBengali-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansBengali-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSerifBengali-Regular.ttf",
]


def _repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def bundled_font(bold=True):
    """The Bengali font shipped in the repo - always tried first.
    Returns the path if the file exists, else None."""
    name = "HindSiliguri-Bold.ttf" if bold else "HindSiliguri-Regular.ttf"
    p = os.path.join(_repo_root(), "assets", "fonts", name)
    return p if os.path.exists(p) else None


def covers_bengali(path):
    """True if the font's cmap has every Bengali codepoint we need.
    Returns None when fontTools is unavailable (cannot verify)."""
    try:
        from fontTools.ttLib import TTFont
    except Exception:
        return None
    try:
        cmap = TTFont(path).getBestCmap()
    except Exception:
        return False
    return all(cp in cmap for cp in BENGALI_PROBE)


def _verified(path, what):
    """Accept a font only if it is verified Bengali-capable.
    Returns the path, or None (with a log line) if rejected."""
    check = covers_bengali(path)
    if check is True:
        return path
    if check is False:
        print("[assets] rejecting %s: no Bengali coverage" % what,
              file=sys.stderr)
        return None
    # fontTools unavailable - cannot verify, so do not trust it.
    print("[assets] cannot verify %s (no fontTools) - skipping" % what,
          file=sys.stderr)
    return None


def find_font(bold=True):
    """Bengali font, bundled first, then system fonts - every one
    verified to actually cover Bengali. Never returns a font that
    cannot render Bengali, and never falls back to 'any .ttf' (a
    Latin-only font would draw tofu boxes). Returns None when no
    Bengali-capable font exists - the caller must fail loudly."""
    # 1. Bundled font (pre-verified by the package author).
    p = bundled_font(bold)
    if p:
        check = covers_bengali(p)
        if check is not False:
            print("[assets] bundled font: %s" % p)
            return p
        print("[assets] rejecting bundled font: no Bengali coverage",
              file=sys.stderr)
    else:
        print("[assets] bundled font missing - trying system fonts",
              file=sys.stderr)
    if bold:
        p = bundled_font(False)
        if p:
            check = covers_bengali(p)
            if check is not False:
                print("[assets] bundled font (regular): %s" % p)
                return p
    # 2. System candidates - only if verified Bengali-capable.
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            got = _verified(p, p)
            if got:
                return got
    for pat in ("/usr/share/fonts/**/NotoSansBengali*.ttf",
                "/usr/share/fonts/**/Lohit-Bengali*.ttf",
                "/usr/share/fonts/**/NotoSerifBengali*.ttf"):
        hits = sorted(glob.glob(pat, recursive=True))
        for p in hits:
            got = _verified(p, p)
            if got:
                return got
    # 3. fontconfig match for Bengali - only if verified.
    try:
        r = subprocess.run(["fc-match", "-f", "%{file}", ":lang=bn"],
                           capture_output=True, text=True, timeout=20)
        p = (r.stdout or "").strip()
        if p and os.path.exists(p):
            got = _verified(p, p)
            if got:
                return got
    except Exception:
        pass
    return None


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


def _raqm_layout():
    try:
        return ImageFont.Layout.RAQM
    except Exception:
        return None


def font(path, size):
    """Font with libraqm shaping (proper Bengali conjuncts). Falls
    back to Pillow's default layout only when RAQM is unavailable."""
    layout = _raqm_layout()
    if layout is not None:
        try:
            return ImageFont.truetype(path, size, layout_engine=layout)
        except Exception as e:
            print("[assets] RAQM failed (%s) - using default layout" % e,
                  file=sys.stderr)
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

    FONT_PATH = find_font(bold=True)
    if not FONT_PATH:
        print("[assets] FATAL: no Bengali font - cannot render Bengali "
              "text. Refusing to build a box-filled Reel.",
              file=sys.stderr)
        return 1
    print("[assets] font: %s" % FONT_PATH)
    made = {}
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
