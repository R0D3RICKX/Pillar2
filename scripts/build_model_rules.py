#!/usr/bin/env python3
"""Build the static GloBE Model Rules website from All.pdf.

The OECD GloBE Model Rules (Pillar Two, December 2021) occupy PDF pages 9-69
of All.pdf. This script extracts that text with poppler's `pdftotext -layout`,
parses it into chapters, articles, paragraphs and definitions, and writes a
static site (one page per article) that deploys to Vercel as-is.

Usage:  python3 scripts/build_model_rules.py        (run from the repo root)
Needs:  poppler-utils (pdftotext, pdftohtml)
"""

import html
import json
import re
import subprocess
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / "All.pdf"
FIRST_PAGE, LAST_PAGE = 9, 69          # PDF page numbers of Chapters 1-10
DEF_PAGES = (53, 68)                   # PDF pages holding Article 10.1
PDF_VIEWER = "/pdfjs/web/viewer.html?file=../../All.pdf#page={page}"
SITE_TITLE = "GloBE Model Rules (Pillar Two)"

CHAPTERS = {
    1: "Scope",
    2: "Charging Provisions",
    3: "Computation of GloBE Income or Loss",
    4: "Computation of Adjusted Covered Taxes",
    5: "Computation of Effective Tax Rate and Top-up Tax",
    6: "Corporate Restructurings and Holding Structures",
    7: "Tax Neutrality and Distribution Regimes",
    8: "Administration",
    9: "Transition Rules",
    10: "Definitions",
}

ARTICLES = {
    "1.1": "Scope of GloBE Rules",
    "1.2": "MNE Group and Group",
    "1.3": "Constituent Entity",
    "1.4": "Ultimate Parent Entity",
    "1.5": "Excluded Entity",
    "2.1": "Application of the IIR",
    "2.2": "Allocation of Top-Up Tax under the IIR",
    "2.3": "IIR Offset Mechanism",
    "2.4": "Application of the UTPR",
    "2.5": "UTPR Top-up Tax Amount",
    "2.6": "Allocation of Top-Up Tax for the UTPR",
    "3.1": "Financial Accounts",
    "3.2": "Adjustments to determine GloBE Income or Loss",
    "3.3": "International Shipping Income exclusion",
    "3.4": "Allocation of Income or Loss between a Main Entity and a Permanent Establishment",
    "3.5": "Allocation of Income or Loss from a Flow-through Entity",
    "4.1": "Adjusted Covered Taxes",
    "4.2": "Definition of Covered Taxes",
    "4.3": "Allocation of Covered Taxes from one Constituent Entity to another Constituent Entity",
    "4.4": "Mechanism to address temporary differences",
    "4.5": "The GloBE Loss Election",
    "4.6": "Post-filing Adjustments and Tax Rate Changes",
    "5.1": "Determination of Effective Tax Rate",
    "5.2": "Top-up Tax",
    "5.3": "Substance-based Income Exclusion",
    "5.4": "Additional Current Top-up Tax",
    "5.5": "De minimis exclusion",
    "5.6": "Minority-Owned Constituent Entities",
    "6.1": "Application of Consolidated Revenue Threshold to Group Mergers and Demergers",
    "6.2": "Constituent Entities joining and leaving an MNE Group",
    "6.3": "Transfer of Assets and Liabilities",
    "6.4": "Joint Ventures",
    "6.5": "Multi-Parented MNE Groups",
    "7.1": "Ultimate Parent Entity that is a Flow-through Entity",
    "7.2": "Ultimate Parent Entity subject to Deductible Dividend Regime",
    "7.3": "Eligible Distribution Tax Systems",
    "7.4": "Effective Tax Rate Computation for Investment Entities",
    "7.5": "Investment Entity Tax Transparency Election",
    "7.6": "Taxable Distribution Method Election",
    "8.1": "Filing obligation",
    "8.2": "Safe Harbours",
    "8.3": "Administrative Guidance",
    "9.1": "Tax Attributes Upon Transition",
    "9.2": "Transitional relief for the Substance-based Income Exclusion",
    "9.3": "Exclusion from the UTPR of MNE Groups in the initial phase of their international activity",
    "9.4": "Transitional relief for filing obligations",
    "10.1": "Defined Terms",
    "10.2": "Definitions of Flow-through Entity, Tax Transparent Entity, Reverse Hybrid Entity, and Hybrid Entity",
    "10.3": "Location of an Entity and a Permanent Establishment",
}


# Formulas are typeset with Cambria Math and come out of pdftotext as scattered
# fragments, so each one is rewritten from the source. Keyed by the start of
# the first fragment line (after NFKC normalisation).
def frac(num, den):
    return (f'<span class="frac"><span class="num">{num}</span>'
            f'<span class="den">{den}</span></span>')


FORMULAS = {
    "Number of Employees in the jurisdiction": (
        "UTPR Percentage = 50% × "
        + frac("Number of Employees in the jurisdiction",
               "Number of Employees in all UTPR jurisdictions")
        + " + 50% × "
        + frac("Total value of Tangible Assets in the jurisdiction",
               "Total value of Tangible Assets in all UTPR jurisdictions")),
    "Allocated Asset Gain for relevant year": (
        "Allocated Asset Gain for relevant year × "
        + frac("The specified Constituent Entity’s Net Asset Gain in the Election Year",
               "The Net Asset Gain of all specified Constituent Entities in the Election Year")),
    "Net GloBE Income =": (
        "Net GloBE Income = GloBE Income of all Constituent Entities − "
        "GloBE Losses of all Constituent Entities"),
    "Top up Tax Percentage =": "Top-up Tax Percentage = Minimum Rate − Effective Tax Rate",
    "Excess Profit =": "Excess Profit = Net GloBE Income − Substance-based Income Exclusion",
    "Jurisdictional Top up Tax": (
        "Jurisdictional Top-up Tax = (Top-up Tax Percentage × Excess Profit) "
        "+ Additional Current Top-up Tax − Domestic Top-up Tax"),
    "GloBE Income of the CE": (
        "Top-up Tax of a CE = Jurisdictional Top-up Tax × "
        + frac("GloBE Income of the CE", "Aggregate GloBE Income of all CEs")),
    "(GloBE Income or Loss x Minimum Rate)": (
        "(GloBE Income or Loss × Minimum Rate) − Adjusted Covered Taxes"),
    "GloBE Income of the CE#7.3.8": (
        "Disposition Recapture Ratio = "
        + frac("GloBE Income of the CE", "Net Income of the jurisdiction")),
    "Net GloBE Loss =": (
        "Net GloBE Loss = GloBE Income of all Constituent Entities − "
        "GloBE Losses of all Constituent Entities"),
}

MATH = re.compile("[\U0001D400-\U0001D7FF]")
ROMAN = re.compile(r"^(i|ii|iii|iv|v|vi|vii|viii|ix|x|xi|xii)$")


def esc(s):
    return html.escape(s, quote=True)


def slug(term):
    s = unicodedata.normalize("NFKD", term).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------

def extract_pages():
    out = subprocess.run(
        ["pdftotext", "-layout", "-f", str(FIRST_PAGE), "-l", str(LAST_PAGE),
         str(PDF), "-"], capture_output=True, text=True, check=True).stdout
    return out.split("\f")[: LAST_PAGE - FIRST_PAGE + 1]


def extract_defined_terms():
    """Bold runs at the left margin of Article 10.1 are the defined terms."""
    xml = subprocess.run(
        ["pdftohtml", "-xml", "-i", "-stdout", "-f", str(DEF_PAGES[0]),
         "-l", str(DEF_PAGES[1]), str(PDF)],
        capture_output=True, text=True, check=True).stdout
    terms, cur, cur_top = [], None, None
    for m in re.finditer(r'<text top="(\d+)" left="(\d+)"[^>]*>(.*?)</text>', xml):
        top, left, body = int(m[1]), int(m[2]), m[3]
        bold = re.fullmatch(r"<b>(.*)</b>", body.strip())
        if bold and left < 105 and bold[1].strip():
            if cur is not None:
                terms.append(cur)
            cur, cur_top = bold[1], top
        elif bold and cur is not None and top == cur_top:
            cur += bold[1]
        else:
            if cur is not None:
                terms.append(cur)
            cur = None
    if cur is not None:
        terms.append(cur)
    clean = []
    for t in terms:
        t = html.unescape(re.sub(r"<[^>]+>", "", t))
        t = re.sub(r"\s+", " ", t).strip().rstrip(",")
        if t and t[0].isupper() and not t.startswith("Article") and t not in clean:
            clean.append(t)
    # Longest first so "Net GloBE Income" wins over "Net GloBE".
    return sorted(clean, key=len, reverse=True)


# --------------------------------------------------------------------------
# Line classification
# --------------------------------------------------------------------------

def prepare_lines(pages):
    """Yield (pdf_page, indent, text) with headers, footers and formulas
    handled. Formula fragments collapse into a single ('@@F', html) line."""
    lines = []
    for i, page in enumerate(pages):
        pno = FIRST_PAGE + i
        raw = page.split("\n")
        j = 0
        while j < len(raw):
            line = raw[j].rstrip()
            j += 1
            if "© OECD 2021" in line or re.fullmatch(r"[\W_]*\d{1,3}[\W_]*", line):
                continue
            if MATH.search(line):
                # Gather the whole fragment block (fraction bars, operators).
                block = [line]
                while j < len(raw) and (MATH.search(raw[j]) or re.fullmatch(
                        r"\s*(×|50% x\s+\+ 50% x|=?.*𝑇𝑜𝑝.*)\s*", raw[j])):
                    block.append(raw[j])
                    j += 1
                first = re.sub(r"\s+", " ", unicodedata.normalize(
                    "NFKC", block[0])).strip()
                if first.startswith("50% x"):
                    first = re.sub(r"\s+", " ", unicodedata.normalize(
                        "NFKC", block[1])).strip()
                key = next((k for k in FORMULAS if first.startswith(k.split("#")[0])),
                           None)
                if key == "GloBE Income of the CE" and any(
                        "Net Income of the jurisdiction" in unicodedata.normalize("NFKC", b)
                        for b in block):
                    key = "GloBE Income of the CE#7.3.8"
                if key is None:
                    raise SystemExit(f"Unknown formula on page {pno}: {first!r}")
                lines.append((pno, 0, "@@F" + FORMULAS[key]))
                continue
            if line.strip() == "50% x":
                continue
            text = line.strip()
            indent = len(line) - len(line.lstrip()) if text else 0
            lines.append((pno, indent, text))
    return lines


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------

class Block:
    """A run of text: a numbered paragraph, a lettered/roman sub-item, or an
    unlabelled sentence (e.g. "Where:")."""

    def __init__(self, kind, label, text, level, page, indent, text_col):
        self.kind, self.label, self.level = kind, label, level
        self.parts = [text] if text else []
        self.page, self.indent, self.text_col = page, indent, text_col
        self.last_page = page

    @property
    def text(self):
        out = ""
        for p in self.parts:
            if not out:
                out = p
            elif re.search(r"[A-Za-z]-$", out):
                out += p  # line broke inside a hyphenated compound (Low-|Taxed)
            else:
                out += " " + p
        return out

    def to_dict(self):
        d = {"type": self.kind, "level": self.level, "text": self.text}
        if self.label:
            d["label"] = self.label
        return d


def parse(lines, terms):
    chapters = []
    chapter = article = para = None
    defn = None
    stack = []          # [(indent, level, label, page)] of open sub-items
    last_block = None
    expected_ch = 1
    art_keys = list(ARTICLES)
    next_art = 0
    in_intro = False
    table = None
    pending_title = None

    def new_block(container, block):
        nonlocal last_block
        container.append(block)
        last_block = block
        return block

    def body():
        """The block list currently receiving content."""
        if defn is not None:
            return defn["blocks"]
        if para is not None:
            return para["blocks"]
        return article["preamble"]

    i = 0
    while i < len(lines):
        page, indent, text = lines[i]
        i += 1

        if pending_title is not None:
            if text and not text.startswith(tuple("0123456789")):
                article["_raw_title"] += " " + text
                if article["_raw_title"].endswith(ARTICLES[article["id"]]) or \
                        len(article["_raw_title"]) >= len(ARTICLES[article["id"]]):
                    pending_title = None
                continue
            pending_title = None

        if not text:
            if table is not None:
                table = None
            continue

        # ---- chapter heading -------------------------------------------
        m = re.fullmatch(rf"{expected_ch} ([A-Z].*)", text) if expected_ch <= 10 else None
        if m and any("Operation of the rules" in l[2] for l in lines[i:i + 3]):
            chapter = {"number": expected_ch, "title": CHAPTERS[expected_ch],
                       "page": page, "intro": [], "articles": []}
            chapters.append(chapter)
            expected_ch += 1
            article = para = defn = None
            in_intro = True
            # skip wrapped title line(s) and the "Operation of the rules" label
            while i < len(lines) and "Operation of the rules" not in lines[i][2]:
                i += 1
            i += 1
            continue

        # ---- article heading -------------------------------------------
        if next_art < len(art_keys):
            key = art_keys[next_art]
            if text.startswith(f"Article {key}. "):
                article = {"id": key, "title": ARTICLES[key], "page": page,
                           "chapter": chapter["number"], "preamble": [],
                           "paragraphs": [], "definitions": [],
                           "_raw_title": text[len(f"Article {key}. "):]}
                chapter["articles"].append(article)
                next_art += 1
                para = defn = None
                stack = []
                in_intro = False
                if not ARTICLES[key].startswith(article["_raw_title"]) or \
                        article["_raw_title"] != ARTICLES[key]:
                    pending_title = True
                continue

        if in_intro:
            if text.startswith("•"):
                chapter["intro"].append({"type": "bullet", "text": text.lstrip("• ").strip()})
            elif text.startswith("Article") and chapter["intro"] and \
                    chapter["intro"][-1]["type"] == "bullet" and chapter["intro"][-1]["text"] == "":
                chapter["intro"][-1]["text"] = text
            elif chapter["intro"] and (indent >= 6 or not text[0].isupper()) and \
                    chapter["intro"][-1]["type"] == "bullet":
                chapter["intro"][-1]["text"] += " " + text
            elif chapter["intro"] and chapter["intro"][-1]["type"] == "text" and \
                    not chapter["intro"][-1]["text"].endswith("."):
                chapter["intro"][-1]["text"] += " " + text
            else:
                chapter["intro"].append({"type": "text", "text": text})
            continue

        # ---- formula ---------------------------------------------------
        if text.startswith("@@F"):
            new_block(body(), Block("formula", None, text[3:], 0, page, 0, 0))
            continue

        # ---- tables (Article 9.2) --------------------------------------
        m = re.fullmatch(r"(Fiscal Year Beginning In)\s{2,}(.+)", text)
        if m:
            table = {"type": "table", "header": [m[1], m[2]], "rows": []}
            body().append(table)
            last_block = None
            continue
        if table is not None:
            m = re.fullmatch(r"(20\d\d)\s+([\d.]+%)", text)
            if m:
                table["rows"].append([m[1], m[2]])
                continue
            table = None

        # ---- definitions (Article 10.1) --------------------------------
        if article and article["id"] == "10.1" and indent <= 1 and (
                last_block is None or last_block.text.rstrip().endswith((".", ":"))
                or re.search(r"defined in Article [\d.]+(\([a-z]\))?$", last_block.text)):
            term = next((t for t in terms if text.startswith(t) and (
                len(text) == len(t) or not text[len(t)].isalnum())), None)
            if term:
                defn = {"term": term, "id": slug(term), "page": page, "blocks": []}
                article["definitions"].append(defn)
                stack = []
                new_block(defn["blocks"], Block("text", None, text, 0, page, indent, indent))
                continue

        # ---- numbered paragraph ----------------------------------------
        m = re.match(r"(\d+\.\d+\.\d+)\.(?:\s+(.*))?$", text)
        if m and article and m[1].rsplit(".", 1)[0] == article["id"]:
            para = {"id": m[1], "page": page, "blocks": []}
            article["paragraphs"].append(para)
            defn = None
            stack = []
            col = indent + len(text) - len(m[2] or "")
            new_block(para["blocks"], Block("para", m[1], m[2] or "", 0, page, indent, col))
            continue

        # ---- lettered / roman sub-item ---------------------------------
        m = re.match(r"(\(([a-z]{1,4})\)|([ivx]+)\.)\s+(.*)$", text)
        if m and last_block is not None and re.search(
                r"\([a-z]+\) (to|and|or|through)$", last_block.text):
            m = None  # wrapped range such as "paragraphs (a) to / (d) below"
        if m:
            raw = m[2] or m[3]
            label = m[1]
            # Determine nesting level from indentation (same page) or label type.
            while stack and stack[-1][3] == page and stack[-1][0] > indent + 1:
                stack.pop()
            if stack and stack[-1][3] == page and abs(stack[-1][0] - indent) <= 1:
                level = stack[-1][1]
                stack[-1] = (indent, level, raw, page)
            elif stack and stack[-1][3] == page and stack[-1][0] < indent:
                level = stack[-1][1] + 1
                stack.append((indent, level, raw, page))
            else:
                # New page or first item: infer from the label sequence.
                is_roman = bool(ROMAN.match(raw)) or m[3] is not None
                prev_letters = [s for s in stack if not ROMAN.match(s[2]) or s[2] in ("i", "v", "x")]
                if is_roman and stack and (m[3] is not None or raw != chr(ord(stack[0][2][-1]) + 1)
                                           and not (raw == "i" and stack[0][2] == "h")):
                    level = stack[0][1] + 1 if stack else 2
                    stack = [s for s in stack if s[1] < level] + [(indent, level, raw, page)]
                else:
                    level = 1
                    stack = [(indent, level, raw, page)]
                del prev_letters
            col = indent + len(text) - len(m[4])
            new_block(body(), Block("item", label, m[4], level, page, indent, col))
            continue

        # ---- continuation or free text ---------------------------------
        if article is None:
            continue
        lb = last_block
        if lb is not None:
            prev = lb.text.rstrip()
            if lb.last_page == page:
                threshold = lb.indent - 2 if lb.kind == "para" else lb.text_col - 2
                if lb.kind == "text":
                    threshold = lb.indent - 2
                cont = indent >= threshold
                if cont and lb.kind == "text" and lb.level == 0 and prev.endswith(":") \
                        and defn is None:
                    cont = False
            else:
                cont = not (prev.endswith((".", ":")) and text[0].isupper())
            if not prev.endswith((".", ":", ";")):
                cont = True
            if lb.kind == "formula":
                cont = False
            if cont:
                lb.parts.append(text)
                lb.last_page = page
                continue
        # free-standing sentence
        if para is not None and defn is None:
            base = para["blocks"][0].indent
            level = 0 if indent <= base + 2 else max(1, stack[-1][1] if stack else 1)
        else:
            level = 0 if indent <= 2 else 1
        stack = [s for s in stack if s[1] < level] if level else []
        new_block(body(), Block("text", None, text, level, page, indent, indent))

    # finalise
    for ch in chapters:
        for art in ch["articles"]:
            art.pop("_raw_title", None)
            art["preamble"] = [b.to_dict() if isinstance(b, Block) else b for b in art["preamble"]]
            for p in art["paragraphs"]:
                p["blocks"] = [b.to_dict() if isinstance(b, Block) else b for b in p["blocks"]]
            for d in art["definitions"]:
                d["blocks"] = [b.to_dict() if isinstance(b, Block) else b for b in d["blocks"]]
    return chapters


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

ART_REF = re.compile(
    r"\b(Articles?|Chapters?)\s+((?:\d+(?:\.\d+)*(?:\([a-z]+\))?)"
    r"(?:(?:,\s*|\s+(?:and|or|to|through)\s+|\s*-\s*)(?:Article\s+)?\d+(?:\.\d+)*(?:\([a-z]+\))?)*)")
NUM_REF = re.compile(r"\d+(?:\.\d+)*")


def ref_url(num):
    parts = num.split(".")
    if len(parts) == 1:
        return f"/chapters/{parts[0]}" if parts[0] in map(str, CHAPTERS) else None
    art = ".".join(parts[:2])
    if art not in ARTICLES:
        return None
    if len(parts) == 2:
        return f"/articles/{art}"
    return f"/articles/{art}#{'.'.join(parts[:3])}"


def link_refs(text, here=None):
    """Escape text and hyperlink cross-references such as 'Article 3.2.6'."""
    out, pos = [], 0
    for m in ART_REF.finditer(text):
        out.append(esc(text[pos:m.start(2)]))
        seg, p2 = m[2], 0
        for n in NUM_REF.finditer(seg):
            out.append(esc(seg[p2:n.start()]))
            url = ref_url(n[0])
            if url and here and url.startswith(f"/articles/{here}#"):
                url = url[len(f"/articles/{here}"):]
            out.append(f'<a class="xref" href="{url}">{n[0]}</a>' if url else esc(n[0]))
            p2 = n.end()
        out.append(esc(seg[p2:]))
        pos = m.end()
    out.append(esc(text[pos:]))
    return "".join(out)


def render_blocks(blocks, here):
    out = []
    for b in blocks:
        if b["type"] == "table":
            rows = "".join(f"<tr><td>{esc(r[0])}</td><td>{esc(r[1])}</td></tr>" for r in b["rows"])
            out.append(f'<table class="rate"><thead><tr><th>{esc(b["header"][0])}</th>'
                       f'<th>{esc(b["header"][1])}</th></tr></thead><tbody>{rows}</tbody></table>')
        elif b["type"] == "formula":
            wide = " wide" if "frac" in b["text"] else ""
            out.append(f'<div class="formula{wide}" role="math">{b["text"]}</div>')
        elif b["type"] == "para":
            out.append(f'<p class="lvl0">{link_refs(b["text"], here)}</p>')
        elif b["type"] == "item":
            out.append(f'<p class="lvl{b["level"]} item"><span class="lbl">{esc(b["label"])}</span>'
                       f'<span>{link_refs(b["text"], here)}</span></p>')
        else:
            out.append(f'<p class="lvl{b["level"]}">{link_refs(b["text"], here)}</p>')
    return "\n".join(out)


def render_definition_text(d):
    blocks = list(d["blocks"])
    first = dict(blocks[0])
    rest = first["text"][len(d["term"]):]
    head = f'<p class="lvl0"><dfn>{esc(d["term"])}</dfn>{link_refs(rest)}</p>'
    return head + "\n" + render_blocks(blocks[1:], None)


def page(title, description, body, canonical, nav_html="", extra_head=""):
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<link rel="canonical" href="{canonical}">
<link rel="stylesheet" href="/assets/style.css">
<link rel="alternate" type="application/json" href="/model-rules.json" title="Model Rules as JSON">
{extra_head}</head>
<body>
<header class="top">
  <a class="brand" href="/">{esc(SITE_TITLE)}</a>
  <nav class="toplinks"><a href="/#contents">Contents</a><a href="/definitions">Definitions</a><a href="/search">Search</a><a href="/viewer">PDF</a></nav>
</header>
<div class="wrap">
<nav class="toc" aria-label="Table of contents">{nav_html}</nav>
<main id="main">
{body}
</main>
</div>
<footer class="foot">Text: OECD (2021), <cite>Tax Challenges Arising from the Digitalisation of the Economy – Global Anti-Base Erosion Model Rules (Pillar Two)</cite>, OECD Publishing, Paris. © OECD 2021. Unofficial HTML rendering for navigation; the PDF is authoritative.</footer>
<script src="/assets/site.js" defer></script>
</body>
</html>
"""


def toc_html(chapters, current=None):
    out = ['<ol class="toc-ch">']
    for ch in chapters:
        open_ = " open" if current and current.startswith(f"{ch['number']}.") else ""
        out.append(f'<li><details{open_}><summary><a href="/chapters/{ch["number"]}">'
                   f'{ch["number"]}. {esc(ch["title"])}</a></summary><ol>')
        for a in ch["articles"]:
            cur = ' aria-current="page"' if a["id"] == current else ""
            out.append(f'<li><a href="/articles/{a["id"]}"{cur}><span class="n">{a["id"]}</span> '
                       f'{esc(a["title"])}</a></li>')
        out.append("</ol></details></li>")
    out.append("</ol>")
    return "".join(out)


def article_body(a, prev, nxt, chapter):
    parts = [f'<p class="crumbs"><a href="/">Model Rules</a> › <a href="/chapters/{chapter["number"]}">'
             f'Chapter {chapter["number"]}: {esc(chapter["title"])}</a></p>',
             f'<article class="article" id="article-{a["id"]}" data-article="{a["id"]}">',
             f'<h1><span class="n">Article {a["id"]}.</span> {esc(a["title"])}</h1>',
             f'<p class="meta"><a href="{PDF_VIEWER.format(page=a["page"])}">View in PDF (p. {a["page"]})</a>'
             f' · <a href="/articles/{a["id"]}.json">JSON</a></p>']
    if a["preamble"]:
        parts.append(f'<div class="preamble">{render_blocks(a["preamble"], a["id"])}</div>')
    for p in a["paragraphs"]:
        parts.append(f'<section class="para" id="{p["id"]}" data-ref="{p["id"]}">'
                     f'<a class="pnum" href="#{p["id"]}" title="Link to Article {p["id"]}">{p["id"]}.</a>'
                     f'<div class="ptext">{render_blocks(p["blocks"], a["id"])}</div></section>')
    if a["definitions"]:
        letters = sorted({d["term"][0].upper() for d in a["definitions"]})
        parts.append('<p class="az">' + " ".join(
            f'<a href="#letter-{l}">{l}</a>' for l in letters) + "</p>")
        seen = set()
        parts.append('<dl class="defs">')
        for d in sorted(a["definitions"], key=lambda d: d["term"].lower()):
            l = d["term"][0].upper()
            anchor = f' <span id="letter-{l}"></span>' if l not in seen else ""
            seen.add(l)
            parts.append(f'<div class="def" id="{d["id"]}" data-term="{esc(d["term"])}">{anchor}'
                         f'<a class="pnum" href="#{d["id"]}" title="Link to definition">#</a>'
                         f'{render_definition_text(d)}</div>')
        parts.append("</dl>")
    parts.append("</article>")
    pn = ['<nav class="pager">']
    pn.append(f'<a rel="prev" href="/articles/{prev["id"]}">← Article {prev["id"]}. {esc(prev["title"])}</a>'
              if prev else "<span></span>")
    pn.append(f'<a rel="next" href="/articles/{nxt["id"]}">Article {nxt["id"]}. {esc(nxt["title"])} →</a>'
              if nxt else "<span></span>")
    pn.append("</nav>")
    parts.append("".join(pn))
    return "\n".join(parts)


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build():
    terms = extract_defined_terms()
    chapters = parse(prepare_lines(extract_pages()), terms)
    articles = [a for ch in chapters for a in ch["articles"]]
    assert [a["id"] for a in articles] == list(ARTICLES), "article sequence mismatch"
    by_ch = {ch["number"]: ch for ch in chapters}

    # Article pages + per-article JSON
    for k, a in enumerate(articles):
        prev = articles[k - 1] if k else None
        nxt = articles[k + 1] if k + 1 < len(articles) else None
        ch = by_ch[a["chapter"]]
        desc = f"GloBE Model Rules (Pillar Two) Article {a['id']}: {a['title']}."
        write(ROOT / "articles" / f"{a['id']}.html",
              page(f"Article {a['id']} – {a['title']} | GloBE Model Rules", desc,
                   article_body(a, prev, nxt, ch), f"/articles/{a['id']}", toc_html(chapters, a["id"])))
        write(ROOT / "articles" / f"{a['id']}.json", json.dumps(
            {"chapter": {"number": ch["number"], "title": ch["title"]}, **a,
             "url": f"/articles/{a['id']}"}, ensure_ascii=False, indent=1))

    # Chapter pages
    for ch in chapters:
        intro = []
        bullets = []
        for b in ch["intro"]:
            if b["type"] == "bullet":
                bullets.append(f"<li>{link_refs(b['text'])}</li>")
            else:
                if bullets:
                    intro.append("<ul>" + "".join(bullets) + "</ul>")
                    bullets = []
                intro.append(f"<p>{link_refs(b['text'])}</p>")
        if bullets:
            intro.append("<ul>" + "".join(bullets) + "</ul>")
        items = "".join(
            f'<li><a href="/articles/{a["id"]}"><span class="n">Article {a["id"]}.</span> '
            f'{esc(a["title"])}</a></li>' for a in ch["articles"])
        body = (f'<p class="crumbs"><a href="/">Model Rules</a></p>'
                f'<h1><span class="n">Chapter {ch["number"]}.</span> {esc(ch["title"])}</h1>'
                f'<p class="meta"><a href="{PDF_VIEWER.format(page=ch["page"])}">View in PDF (p. {ch["page"]})</a></p>'
                f'<aside class="intro"><h2>Operation of the rules in this chapter</h2>{"".join(intro)}</aside>'
                f'<h2>Articles</h2><ol class="artlist">{items}</ol>')
        write(ROOT / "chapters" / f"{ch['number']}.html",
              page(f"Chapter {ch['number']} – {ch['title']} | GloBE Model Rules",
                   f"GloBE Model Rules Chapter {ch['number']}: {ch['title']}.", body,
                   f"/chapters/{ch['number']}", toc_html(chapters)))

    # Definitions alias page
    defs = by_ch[10]["articles"][0]["definitions"]
    write(ROOT / "definitions.html", page(
        "Definitions (Article 10.1) | GloBE Model Rules",
        "Alphabetical defined terms of the GloBE Model Rules (Article 10.1).",
        article_body(by_ch[10]["articles"][0], None, by_ch[10]["articles"][1], by_ch[10]),
        "/definitions", toc_html(chapters, "10.1")))

    # Home page
    rows = []
    for ch in chapters:
        rows.append(f'<section class="chap"><h3><a href="/chapters/{ch["number"]}">Chapter {ch["number"]}. '
                    f'{esc(ch["title"])}</a></h3><ol class="artlist">')
        for a in ch["articles"]:
            rows.append(f'<li><a href="/articles/{a["id"]}"><span class="n">{a["id"]}</span> '
                        f'{esc(a["title"])}</a></li>')
        rows.append("</ol></section>")
    home = f"""<h1>GloBE Model Rules (Pillar Two)</h1>
<p class="lede">The OECD/G20 Inclusive Framework Global Anti-Base Erosion Model Rules (December 2021), one page per article, with a stable link for every paragraph and defined term.</p>
<form class="go" action="/search" method="get" role="search">
  <label for="q">Go to an article, paragraph or defined term</label>
  <div class="row"><input id="q" name="q" placeholder="e.g. 3.2.6, 5.3 or Qualified IIR" autocomplete="off"><button>Go</button></div>
</form>
<section class="howto">
<h2>Linking scheme</h2>
<table class="urls"><tbody>
<tr><td>Article</td><td><code>/articles/3.2</code></td></tr>
<tr><td>Paragraph</td><td><code>/articles/3.2#3.2.6</code> or shortcut <code>/3.2.6</code></td></tr>
<tr><td>Chapter</td><td><code>/chapters/5</code></td></tr>
<tr><td>Defined term</td><td><code>/definitions#qualified-iir</code></td></tr>
<tr><td>Machine-readable</td><td><code>/model-rules.json</code>, <code>/articles/3.2.json</code>, <code>/llms.txt</code></td></tr>
</tbody></table>
</section>
<h2 id="contents">Contents</h2>
<div class="contents">{''.join(rows)}</div>"""
    write(ROOT / "index.html", page(SITE_TITLE, "Navigable HTML version of the OECD GloBE Model Rules (Pillar Two), "
                                    "with a stable URL for every article, paragraph and defined term.",
                                    home, "/", toc_html(chapters)))

    # Search page (client-side, uses model-rules.json)
    search = """<h1>Search the Model Rules</h1>
<form class="go" action="/search" method="get" role="search">
  <label for="q">Article number, defined term or words</label>
  <div class="row"><input id="q" name="q" autocomplete="off"><button>Search</button></div>
</form>
<p id="status" class="meta"></p>
<ol id="results" class="results"></ol>"""
    write(ROOT / "search.html", page("Search | GloBE Model Rules", "Search the GloBE Model Rules.",
                                     search, "/search", toc_html(chapters)))

    # Full JSON dataset
    data = {
        "title": "Tax Challenges Arising from the Digitalisation of the Economy – Global Anti-Base Erosion Model Rules (Pillar Two)",
        "publisher": "OECD", "year": 2021, "source_pdf": "/All.pdf",
        "url_scheme": {"article": "/articles/{article}", "paragraph": "/articles/{article}#{paragraph}",
                       "paragraph_shortcut": "/{paragraph}", "chapter": "/chapters/{chapter}",
                       "definition": "/definitions#{slug}"},
        "chapters": [{**{k: v for k, v in ch.items() if k != "articles"},
                      "articles": ch["articles"]} for ch in chapters],
    }
    write(ROOT / "model-rules.json", json.dumps(data, ensure_ascii=False, indent=1))

    # Redirects for paragraph / article shortcuts
    redirects = [{"source": f"/{a['id']}", "destination": f"/articles/{a['id']}", "permanent": False}
                 for a in articles]
    redirects += [{"source": f"/article/{a['id']}", "destination": f"/articles/{a['id']}", "permanent": False}
                  for a in articles]
    for a in articles:
        for p in a["paragraphs"]:
            for src in (f"/{p['id']}", f"/articles/{p['id']}", f"/article/{p['id']}"):
                redirects.append({"source": src, "destination": f"/articles/{a['id']}#{p['id']}",
                                  "permanent": False})
    for d in defs:
        redirects.append({"source": f"/definitions/{d['id']}", "destination": f"/definitions#{d['id']}",
                          "permanent": False})
    redirects += [{"source": f"/chapter/{n}", "destination": f"/chapters/{n}", "permanent": False}
                  for n in CHAPTERS]
    # cleanUrls already serves /articles/3.2 from 3.2.html; the explicit
    # rewrites guard against the dotted ids being read as file extensions.
    rewrites = [{"source": "/articles/:id", "destination": "/articles/:id.html"},
                {"source": "/chapters/:n", "destination": "/chapters/:n.html"}]
    vercel = {"cleanUrls": True, "trailingSlash": False, "redirects": redirects, "rewrites": rewrites,
              "headers": [{"source": "/(.*).json", "headers": [
                  {"key": "Access-Control-Allow-Origin", "value": "*"}]}]}
    write(ROOT / "vercel.json", json.dumps(vercel, indent=1))

    # llms.txt for AI agents
    lines = ["# GloBE Model Rules (Pillar Two)", "",
             "> HTML rendering of the OECD Global Anti-Base Erosion Model Rules (December 2021). "
             "Every article has its own page; every paragraph and defined term has an anchor.", "",
             "## How to navigate", "",
             "- Article: /articles/{chapter}.{article} (e.g. /articles/3.2)",
             "- Paragraph: /articles/{chapter}.{article}#{chapter}.{article}.{paragraph} "
             "(e.g. /articles/3.2#3.2.6), or the shortcut /{paragraph} (e.g. /3.2.6) which redirects there",
             "- Chapter: /chapters/{n} (1-10)",
             "- Defined term: /definitions#{slug} (lower-case, hyphenated, e.g. /definitions#qualified-iir)",
             "- Whole text as JSON: /model-rules.json; one article as JSON: /articles/{id}.json",
             "- Search: /search?q={query}", "", "## Articles", ""]
    for ch in chapters:
        lines.append(f"### Chapter {ch['number']}. {ch['title']}")
        for a in ch["articles"]:
            lines.append(f"- [Article {a['id']}. {a['title']}](/articles/{a['id']})")
        lines.append("")
    lines += ["## Defined terms", ""]
    lines += [f"- [{d['term']}](/definitions#{d['id']})" for d in sorted(defs, key=lambda d: d["term"].lower())]
    write(ROOT / "llms.txt", "\n".join(lines) + "\n")

    # sitemap (relative paths; Vercel host is not known at build time)
    urls = ["/", "/definitions", "/search"] + [f"/chapters/{n}" for n in CHAPTERS] + \
           [f"/articles/{a['id']}" for a in articles]
    write(ROOT / "sitemap.txt", "\n".join(urls) + "\n")

    n_paras = sum(len(a["paragraphs"]) for a in articles)
    print(f"{len(chapters)} chapters, {len(articles)} articles, {n_paras} paragraphs, {len(defs)} definitions")


if __name__ == "__main__":
    build()
