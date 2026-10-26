#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Page editing: erase things off a page, and put text or images in their place.

The hard part of replacing text in a PDF is not erasing it — it is writing the
new text so it looks like it always belonged. A PDF stores glyphs at fixed
positions, not paragraphs, and the font is usually embedded in the file itself.
So the approach here is:

  1. Read the exact span under the region: font name, size, colour, bold/italic.
  2. Try to reuse the *embedded* font, byte for byte, so the replacement is set
     in the original typeface rather than a lookalike.
  3. Fall back, in order, to the standard PDF font of the same name, then a
     matching family installed on this machine, then the bundled Arabic face —
     and say plainly which one was used.

Step 2 fails more often than you would hope: most PDFs embed only the glyphs
they actually use ("subsetting"), which strips the character map. Such a font
can render the original text and nothing else, so it is detected and skipped
rather than producing blank boxes.
"""

import io
import os
import re
import glob
import tempfile

import pymupdf

SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")
BOLD_WORDS = ("bold", "black", "heavy", "semibold", "demibold", "extrabold")
ITALIC_WORDS = ("italic", "oblique")

# The 14 fonts every PDF viewer has built in. Matching one of these by name is
# as good as reusing the original — they are the same typeface.
BASE14 = {
    "helvetica": ("helv", "hebo", "heit", "hebi"),
    "arial":     ("helv", "hebo", "heit", "hebi"),
    "times":     ("tiro", "tibo", "tiit", "tibi"),
    "timesnewroman": ("tiro", "tibo", "tiit", "tibi"),
    "courier":   ("cour", "cobo", "coit", "cobi"),
    "couriernew": ("cour", "cobo", "coit", "cobi"),
    "symbol":    ("symb", "symb", "symb", "symb"),
    "zapfdingbats": ("zadb", "zadb", "zadb", "zadb"),
}

FONT_DIRS = [
    r"C:\Windows\Fonts",
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts"),
    "/System/Library/Fonts", "/System/Library/Fonts/Supplemental", "/Library/Fonts",
    os.path.expanduser("~/Library/Fonts"),
    "/usr/share/fonts", "/usr/local/share/fonts", os.path.expanduser("~/.fonts"),
]

_system_index = None


# ---------------------------------------------------------------------------
# Font identification
# ---------------------------------------------------------------------------
def clean_font_name(name):
    """'ABCDEF+Arial-BoldMT' -> ('Arial', bold=True, italic=False)"""
    n = SUBSET_PREFIX.sub("", str(name or ""))
    low = n.lower()
    bold = any(w in low for w in BOLD_WORDS)
    italic = any(w in low for w in ITALIC_WORDS)
    fam = re.split(r"[-,_+]", n)[0]
    fam = re.sub(r"(MT|PS|PSMT|Std|Pro|Regular)$", "", fam, flags=re.I)
    return fam.strip() or n, bold, italic


def style_index(bold, italic):
    return (1 if bold else 0) + (2 if italic else 0)


def build_system_index():
    """Map family name -> {(bold, italic): path} from the fonts installed here."""
    global _system_index
    if _system_index is not None:
        return _system_index
    index = {}
    for d in FONT_DIRS:
        if not d or not os.path.isdir(d):
            continue
        for path in glob.glob(os.path.join(d, "**", "*.tt[fc]"), recursive=True) + \
                    glob.glob(os.path.join(d, "**", "*.otf"), recursive=True):
            stem = os.path.splitext(os.path.basename(path))[0]
            low = stem.lower()
            bold = any(w in low for w in BOLD_WORDS) or low.endswith(("bd", "b"))
            italic = any(w in low for w in ITALIC_WORDS) or low.endswith(("i", "bi"))
            fam = re.split(r"[-_ ]", stem)[0].lower()
            for suffix in ("bd", "bi", "i", "b", "z"):
                if fam.endswith(suffix) and len(fam) > len(suffix) + 2:
                    fam = fam[: -len(suffix)]
                    break
            index.setdefault(fam, {}).setdefault(style_index(bold, italic), path)
    _system_index = index
    return index


def _norm(name):
    return re.sub(r"[^a-z0-9]", "", SUBSET_PREFIX.sub("", str(name or "")).lower())


def usable_embedded_font(doc, page, text, span=None):
    """Return (fontfile_path, basefont, why) for the embedded font that the
    original text was actually set in, provided it can set `text`.

    A page usually embeds several faces of one family (regular, bold, italic).
    Taking the first one that happens to cover the characters would silently
    turn regular text bold, so candidates are ranked: the exact font of the
    span first, then the same family in the same weight and slant. A different
    weight is never used here — the caller falls back to an installed copy of
    the right weight instead, and says so. Subsetted fonts are rejected."""
    want_raw = _norm((span or {}).get("raw_name", ""))
    want_fam = _norm((span or {}).get("family", ""))
    want_style = style_index(bool((span or {}).get("bold")), bool((span or {}).get("italic")))

    ranked = []
    for entry in page.get_fonts(full=True):
        xref = entry[0]
        try:
            basefont, ext, _ftype, buf = doc.extract_font(xref)
        except Exception:
            continue
        if not buf or not ext or ext == "n/a":
            continue
        fam, bold, italic = clean_font_name(basefont)
        same_style = style_index(bold, italic) == want_style
        if span:
            if want_raw and _norm(basefont) == want_raw:
                rank = 0
            elif want_fam and _norm(fam) == want_fam and same_style:
                rank = 1
            else:
                continue                  # a different face: never swap it in
        else:
            rank = 2 + style_index(bold, italic)   # no reference: prefer the plain face
        ranked.append((rank, xref, basefont, ext, buf))

    reason = "the font embedded in this PDF cannot set new text"
    for rank, xref, basefont, ext, buf in sorted(ranked, key=lambda r: r[0]):
        try:
            font = pymupdf.Font(fontbuffer=buf)
            codepoints = set(font.valid_codepoints())
        except Exception:
            continue
        if not codepoints:
            reason = "the original font is embedded as a subset (only the letters already used)"
            continue
        if any(ord(c) not in codepoints for c in text):
            reason = "the original font is missing some of the new characters"
            continue
        tmp = tempfile.NamedTemporaryFile(suffix="." + ext, delete=False)
        tmp.write(buf)
        tmp.close()
        return tmp.name, SUBSET_PREFIX.sub("", basefont), None
    if span and not ranked:
        reason = "the original font is not embedded in this PDF"
    return None, None, reason


def merge_glyph_hits(page, hits, query):
    """Searching Latin text returns one rectangle per match. Searching Arabic
    returns one rectangle per *glyph*, so a five-letter word comes back as five
    separate hits. Stitch neighbouring glyphs back into whole matches."""
    if not hits:
        return []
    sample = hits[: min(4, len(hits))]
    per_glyph = all(len((page.get_textbox(r) or "").strip()) <= 1 for r in sample)
    if not per_glyph:
        return hits

    # The glyphs of one match come back consecutively, so grouping in the
    # returned order is reliable — a new match starts wherever the next glyph
    # is no longer touching the previous one. Counting glyphs is not: shaping
    # turns some letter pairs into a single glyph, so the count varies.
    clusters, current = [], []
    for r in hits:
        if current:
            prev = current[-1]
            same_line = abs(r.y0 - prev.y0) < max(2.0, prev.height * 0.5)
            gap = max(r.x0 - prev.x1, prev.x0 - r.x1)   # either direction
            if same_line and gap < max(3.0, prev.height * 0.7):
                current.append(r)
                continue
            clusters.append(current)
            current = []
        current.append(r)
    if current:
        clusters.append(current)

    merged = []
    for cluster in clusters:
        box = cluster[0]
        for r in cluster[1:]:
            box = box | r
        merged.append(box)
    return merged


def span_at(page, rect, tolerance=1.0):
    """The text span overlapping `rect` — the source of truth for what the
    replacement should look like."""
    target = pymupdf.Rect(rect)
    grown = pymupdf.Rect(target.x0 - tolerance, target.y0 - tolerance,
                         target.x1 + tolerance, target.y1 + tolerance)
    best, best_area = None, 0
    try:
        blocks = page.get_text("dict")["blocks"]
    except Exception:
        return None
    for blk in blocks:
        for line in blk.get("lines", []):
            for sp in line.get("spans", []):
                sr = pymupdf.Rect(sp["bbox"])
                inter = sr & grown
                area = abs(inter) if not inter.is_empty else 0
                if area > best_area:
                    best, best_area = sp, area
    if not best:
        return None
    fam, bold, italic = clean_font_name(best["font"])
    colour = int(best.get("color", 0))
    return {
        "raw_name": SUBSET_PREFIX.sub("", best["font"]),
        "family": fam,
        "bold": bold,
        "italic": italic,
        "size": round(float(best["size"]), 2),
        "color": "#%06x" % (colour & 0xFFFFFF),
        "rgb": ((colour >> 16 & 255) / 255, (colour >> 8 & 255) / 255, (colour & 255) / 255),
        "text": best.get("text", ""),
        "bbox": list(best["bbox"]),
        "origin": list(best.get("origin") or (best["bbox"][0], best["bbox"][3])),
    }


def resolve_font(doc, page, span, text, arabic_font_path=None, want_arabic=False):
    """Pick the font to write `text` with. Returns a dict describing the choice
    so the interface can show the user exactly what happened."""
    bold = bool(span and span.get("bold"))
    italic = bool(span and span.get("italic"))
    family = (span or {}).get("family", "")
    idx = style_index(bold, italic)

    # Arabic can only be set with a face that has Arabic glyphs. The embedded
    # font is still tried first — it is the one the document actually used.
    if not want_arabic:
        key = re.sub(r"\s+", "", family).lower()
        if key in BASE14:
            return {"fontname": BASE14[key][idx], "fontfile": None,
                    "match": "exact", "used": f"{family} (standard PDF font)"}

    path, basefont, why = usable_embedded_font(doc, page, text, span)
    if path:
        return {"fontname": "EMBD", "fontfile": path, "match": "embedded",
                "used": f"{basefont} (the font embedded in this file)",
                "cleanup": path}

    key = re.sub(r"\s+", "", family).lower()
    if not want_arabic and key in BASE14:
        return {"fontname": BASE14[key][idx], "fontfile": None,
                "match": "exact", "used": f"{family} (standard PDF font)"}

    index = build_system_index()
    entry = index.get(key) or index.get(key.rstrip("0123456789"))
    if entry:
        path = entry.get(idx) or entry.get(0) or next(iter(entry.values()))
        note = "" if entry.get(idx) else " — the exact weight was not installed"
        return {"fontname": "SYSF", "fontfile": path, "match": "family",
                "used": f"{os.path.basename(path)} (installed on this machine){note}"}

    if want_arabic and arabic_font_path:
        return {"fontname": "ARB", "fontfile": arabic_font_path, "match": "fallback",
                "used": f"{os.path.basename(arabic_font_path)} (bundled Arabic font) "
                        f"— the original ({family or 'unknown'}) could not be reused"}

    return {"fontname": BASE14.get(key, ("helv",))[0] if key in BASE14 else "helv",
            "fontfile": None, "match": "fallback",
            "used": f"Helvetica — the original ({family or 'unknown'}) could not be reused",
            "why": why}


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------
def font_object(choice):
    """A measurable Font for the chosen typeface, or None if it can't be built."""
    try:
        if choice.get("fontfile"):
            return pymupdf.Font(fontfile=choice["fontfile"])
        return pymupdf.Font(choice["fontname"])
    except Exception:
        return None


def size_to_fit(choice, text, size, width, floor_ratio=0.62):
    """A replacement is often longer than what it replaces, and a PDF has no
    reflow — the text after it will not move aside. Rather than letting the new
    text run over its neighbours, shrink it until it fits the space the old text
    occupied. Returns (size, overflowed)."""
    if width <= 0:
        return size, False
    font = font_object(choice)
    if font is None:
        return size, False
    try:
        length = font.text_length(text, fontsize=size)
    except Exception:
        return size, False
    if length <= width:
        return size, False
    scaled = size * width / length
    floor = size * floor_ratio
    if scaled >= floor:
        return round(scaled, 2), False
    return round(floor, 2), True     # still too long even at the smallest size


def write_on_line(page, span, text, choice, size, rgb, max_width, rtl=False):
    """Set a single line of text exactly where the original sat: same baseline,
    same starting edge (the right edge for Arabic), same size unless it has to
    shrink to fit `max_width`. Returns (size_used, overflowed) or None."""
    fontname = choice["fontname"]
    fontfile = choice.get("fontfile")
    if fontfile:
        try:
            page.insert_font(fontname=fontname, fontfile=fontfile)
        except Exception:
            return None
    size, overflow = size_to_fit(choice, text, size, max_width)
    font = font_object(choice)
    try:
        length = font.text_length(text, fontsize=size) if font else 0
    except Exception:
        length = 0
    ox, oy = span["origin"]
    x = (span["bbox"][2] - length) if rtl else ox
    try:
        page.insert_text((x, oy), text, fontsize=size, fontname=fontname,
                         fontfile=fontfile, color=rgb)
    except Exception:
        return None
    return size, overflow


def write_into(page, rect, text, choice, size, rgb, align=0, shrink=True,
               fit_width=None):
    """Draw `text` inside `rect`. Returns the size actually used, or None."""
    fontname = choice["fontname"]
    fontfile = choice.get("fontfile")
    if fontfile:
        try:
            page.insert_font(fontname=fontname, fontfile=fontfile)
        except Exception:
            fontname, fontfile = "helv", None

    if fit_width:
        size, _over = size_to_fit(choice, text, size, fit_width)

    box = pymupdf.Rect(rect.x0, rect.y0 - size * 0.35,
                       rect.x1, rect.y1 + size * 0.45)
    used = float(size)
    while used >= 4:
        try:
            rc = page.insert_textbox(box, text, fontsize=used, fontname=fontname,
                                     fontfile=fontfile, color=rgb, align=align)
        except Exception:
            return None
        if rc >= 0:
            return used
        if not shrink:
            return None
        used -= 0.5
    return None
