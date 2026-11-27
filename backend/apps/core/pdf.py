"""Small PDF writer for the server (standard library only): a title block, headed sections of label/value lines or tables,
word-wrapped cells, repeating table headers, and a "Page x of y" footer.

Used for the unit report that is emailed as an attachment. Text uses the built-in Helvetica fonts (WinAnsi), so English and Somali
print correctly; characters outside Latin-1 and common punctuation print as "?". Nothing here touches the database or Django.
"""
from typing import Sequence

PAGE_W, PAGE_H, MARGIN = 595, 842, 48  # A4 portrait, points
BODY_TOP, BODY_BOTTOM = PAGE_H - 96, 64
NAVY, GOLD, GREY = (0.07, 0.12, 0.22), (0.72, 0.56, 0.18), (0.4, 0.43, 0.48)

# Helvetica advance widths for ASCII 32..126 (units per 1000 em), regular and bold.
_REG = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556, 556, 556, 556, 556, 556,
        278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722, 667,
        611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833,
        556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584]
_BOLD = [278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556, 556, 556, 556, 556, 556,
         333, 333, 584, 584, 584, 611, 975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778, 667, 778, 722, 667,
         611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556, 333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889,
         611, 611, 611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584]


def _clean(text) -> str:
    """Printable text as WinAnsi-safe characters (anything else becomes '?')."""
    out = []
    for ch in str(text if text is not None else "").replace("\t", " "):
        if ch in "\r\n":
            out.append(" ")
            continue
        try:
            ch.encode("cp1252")
            out.append(ch)
        except UnicodeEncodeError:
            out.append("?")
    return "".join(out)


def _width(text: str, size: float, bold: bool = False) -> float:
    table = _BOLD if bold else _REG
    return sum((table[ord(c) - 32] if 32 <= ord(c) <= 126 else 556) for c in text) * size / 1000


def _wrap(text: str, size: float, max_w: float, bold: bool = False) -> list[str]:
    words, lines, cur = _clean(text).split(" "), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if _width(trial, size, bold) <= max_w or not cur:
            cur = trial
            while _width(cur, size, bold) > max_w and len(cur) > 1:  # one very long word: cut it
                cut = len(cur)
                while cut > 1 and _width(cur[:cut], size, bold) > max_w:
                    cut -= 1
                lines.append(cur[:cut])
                cur = cur[cut:]
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


class _Page:
    def __init__(self):
        self.ops: list[str] = []

    def text(self, x, y, s, size=10, bold=False, color=(0, 0, 0), right=False):
        s = _clean(s)
        if right:
            x -= _width(s, size, bold)
        r, g, b = color
        self.ops.append(f"BT /{'F2' if bold else 'F1'} {size} Tf {r:.3f} {g:.3f} {b:.3f} rg {x:.2f} {y:.2f} Td ({_esc(s)}) Tj ET")

    def rule(self, x0, x1, y, color=GREY, width=0.5):
        r, g, b = color
        self.ops.append(f"{r:.3f} {g:.3f} {b:.3f} RG {width} w {x0:.2f} {y:.2f} m {x1:.2f} {y:.2f} l S")

    def fill(self, x, y, w, h, color):
        r, g, b = color
        self.ops.append(f"{r:.3f} {g:.3f} {b:.3f} rg {x:.2f} {y:.2f} {w:.2f} {h:.2f} re f")


def build_pdf(title: str, sections: Sequence[dict], *, org: str = "", subtitle: str = "", footer: str = "", page_label: str = "Page") -> bytes:
    """sections: [{"heading": str, "note": str (optional), "columns": [header, ...] (optional), "rows": [[cell, ...], ...]}].
    Without "columns" a section is a list of label/value lines (two cells per row). Column widths are shared equally, except that the
    first column of a table takes half the width when there are three or more columns."""
    pages: list[_Page] = []
    state = {"page": None, "y": 0.0}
    width = PAGE_W - 2 * MARGIN

    def new_page():
        p = _Page()
        pages.append(p)
        p.fill(0, PAGE_H - 64, PAGE_W, 64, NAVY)
        p.fill(0, PAGE_H - 67, PAGE_W, 3, GOLD)
        if org:
            p.text(MARGIN, PAGE_H - 28, org.upper(), 9, True, (0.85, 0.72, 0.35))
        p.text(MARGIN, PAGE_H - 48, title, 15, True, (1, 1, 1))
        state["page"], state["y"] = p, BODY_TOP
        return p

    def need(h):
        if state["y"] - h < BODY_BOTTOM:
            new_page()
            return True
        return False

    new_page()
    if subtitle:
        for line in _wrap(subtitle, 9.5, width):
            state["page"].text(MARGIN, state["y"], line, 9.5, False, GREY)
            state["y"] -= 13
        state["y"] -= 6

    for sec in sections:
        rows = [[_clean(c) for c in r] for r in sec.get("rows", [])]
        cols = [_clean(c) for c in sec.get("columns", [])]
        ncol = len(cols) or 2
        if ncol >= 3:
            first = width * 0.5
            widths = [first] + [(width - first) / (ncol - 1)] * (ncol - 1)
        else:
            widths = [width * 0.62, width * 0.38] if ncol == 2 else [width]
        need(46)
        state["y"] -= 6
        state["page"].text(MARGIN, state["y"], sec.get("heading", ""), 11.5, True, NAVY)
        state["y"] -= 4
        state["page"].rule(MARGIN, MARGIN + width, state["y"], GOLD, 1)
        state["y"] -= 14
        if sec.get("note"):
            for line in _wrap(sec["note"], 9, width):
                need(13)
                state["page"].text(MARGIN, state["y"], line, 9, False, GREY)
                state["y"] -= 12
            state["y"] -= 3

        def head_row():
            if not cols:
                return
            need(16)
            x = MARGIN
            for i, c in enumerate(cols):
                state["page"].text(x + (widths[i] - 4 if i else 0), state["y"], c, 9, True, GREY, right=bool(i))
                x += widths[i]
            state["y"] -= 4
            state["page"].rule(MARGIN, MARGIN + width, state["y"], GREY, 0.4)
            state["y"] -= 11

        head_row()
        for r in rows:
            r = (r + [""] * ncol)[:ncol]
            wrapped = [_wrap(c, 10, widths[i] - 6, bold=False) for i, c in enumerate(r)]
            h = max(len(w) for w in wrapped) * 13
            if need(h + 2) and cols:
                head_row()
            x = MARGIN
            for i, lines in enumerate(wrapped):
                for k, line in enumerate(lines):
                    state["page"].text(x + (widths[i] - 4 if i else 0), state["y"] - k * 13, line, 10, False, (0, 0, 0), right=bool(i))
                x += widths[i]
            state["y"] -= h + 2
        state["y"] -= 4

    total = len(pages)
    for n, p in enumerate(pages, 1):
        p.rule(MARGIN, MARGIN + width, 46, GREY, 0.4)
        p.text(MARGIN, 33, footer, 8, False, GREY)
        p.text(MARGIN + width, 33, f"{page_label} {n} / {total}", 8, False, GREY, right=True)

    # ---- assemble the file ------------------------------------------------------------------------------------------------
    objs: list[bytes] = []

    def add(body: bytes) -> int:
        objs.append(body)
        return len(objs)

    add(b"")  # 1: catalog (filled below)
    add(b"")  # 2: pages (filled below)
    f1 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    f2 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    kids = []
    for p in pages:
        stream = "\n".join(p.ops).encode("cp1252", "replace")
        c = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        pg = add(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] /Contents {c} 0 R "
                 f"/Resources << /Font << /F1 {f1} 0 R /F2 {f2} 0 R >> >> >>".encode())
        kids.append(pg)
    objs[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>".encode()
    info = add(f"<< /Title ({_esc(_clean(title))}) /Producer (Army HQ) >>".encode())

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for o in offsets:
        out += f"{o:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R /Info {info} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
