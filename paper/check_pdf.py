"""Submission compliance of the built PDF, checked against the file itself.

check_numbers.py reads the SOURCE. This reads the artifact that actually gets uploaded, because
the things a conference desk-rejects for are properties of the PDF: page count, page size,
embedded fonts, page numbers, and placeholder text that renders in the manuscript.

EDAS for RIVF 2026 states: "Manuscripts should not contain page numbers, headers or footers."
IEEE requires every font embedded. The CFP caps the paper at 6 pages including references.

Exit code 0 when the PDF is uploadable, 1 otherwise.

    python paper/check_pdf.py
"""

from __future__ import annotations

import re
import sys
import zlib
from pathlib import Path

PDF = Path(__file__).resolve().parent / "main.pdf"
LOG = Path(__file__).resolve().parent / "main.log"
MAX_PAGES = 6
A4_PT = (595.276, 841.89)   # 210 x 297 mm
TOL = 1.0


def inflated_streams(raw: bytes) -> list[bytes]:
    out = []
    for m in re.finditer(rb"stream\r?\n", raw):
        start = m.end()
        end = raw.find(b"endstream", start)
        if end == -1:
            continue
        try:
            out.append(zlib.decompress(raw[start:end]))
        except zlib.error:
            pass
    return out


def content_streams(streams: list[bytes]) -> list[bytes]:
    """Only the streams that draw a page.

    Inflating every stream also inflates the embedded FONT PROGRAMS, whose binary happens to
    contain parenthesised byte runs. Scanning those for text reported a "??" -- an unresolved
    reference -- that was really two bytes inside a Type 1 font. A content stream opens a text
    object with BT and selects a font with Tf, and is almost entirely printable.
    """
    out = []
    for st in streams:
        if b"BT" not in st or b"Tf" not in st:
            continue
        printable = sum(1 for b in st[:4000] if 9 <= b <= 126)
        if printable / max(1, len(st[:4000])) > 0.8:
            out.append(st)
    return out


def page_text(streams: list[bytes]) -> str:
    """Every string drawn on the page, concatenated.

    Text is shown with Tj (one string) and TJ (an array of strings with kerning numbers
    between them), and TeX kerns inside words -- so "TBD" is commonly drawn as (T) -20 (BD).
    Searching per-operator misses it; searching the concatenation does not.
    """
    out = []
    for st in content_streams(streams):
        for m in re.finditer(rb"\((?:[^()\\]|\\.)*\)", st):
            body = m.group(0)[1:-1]
            body = re.sub(rb"\\([()\\])", rb"\1", body)
            out.append(body.decode("latin-1"))
    return "".join(out)


def main() -> int:
    if not PDF.exists():
        print("main.pdf does not exist -- run paper/compile.sh")
        return 1
    raw = PDF.read_bytes()
    streams = inflated_streams(raw)
    fails: list[str] = []
    notes: list[str] = []

    # --- pages ---------------------------------------------------------------------------
    # Count page objects from this PDF, including compressed object streams.
    # Never accept a stale build log or zero detected pages as a valid page count.
    searchable = raw + b"\n" + b"\n".join(streams)
    pages = len(re.findall(rb"/Type\s*/Page\b", searchable))
    if pages == 0:
        fails.append("no page objects found -- cannot verify the page limit")
    print(f"  pages                 : {pages}")
    if pages > MAX_PAGES:
        fails.append(f"{pages} pages, limit is {MAX_PAGES}")

    # --- page size -----------------------------------------------------------------------
    # PDF 1.5+ may hide object definitions inside compressed object streams, so search the
    # inflated streams as well as the raw bytes. Reading only `raw` reported no page size at
    # all and then failed the paper for it.
    searchable = raw + b"\n" + b"\n".join(streams)
    boxes = {tuple(round(float(x), 2) for x in m)
             for m in re.findall(rb"/MediaBox\s*\[\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)",
                                 searchable)}
    sizes = {(round(b[2] - b[0], 2), round(b[3] - b[1], 2)) for b in boxes}
    print(f"  page size (pt)        : {sorted(sizes)}")
    if not sizes:
        fails.append("no /MediaBox found anywhere -- the scan is broken, not the PDF")
    elif len(sizes) != 1:
        fails.append(f"mixed page sizes: {sorted(sizes)}")
    else:
        w, h = next(iter(sizes))
        if abs(w - A4_PT[0]) > TOL or abs(h - A4_PT[1]) > TOL:
            fails.append(f"page is {w}x{h} pt, A4 is {A4_PT[0]}x{A4_PT[1]}")

    # --- fonts embedded ------------------------------------------------------------------
    base = set(re.findall(rb"/BaseFont\s*/([#\w+-]+)", searchable))
    embedded_objs = len(re.findall(rb"/FontFile[23]?[\s/]", searchable))
    names = sorted({b.decode("latin-1").split("+")[-1] for b in base})
    print(f"  fonts referenced      : {len(names)}  {names}")
    print(f"  font programs embedded: {embedded_objs}")
    # A subset-embedded font carries a six-letter tag; a referenced font with no FontFile at
    # all anywhere is the failure IEEE rejects.
    if not names:
        fails.append("no /BaseFont found anywhere -- the scan is broken, not the PDF")
    elif embedded_objs == 0:
        fails.append("no font programs embedded")
    elif embedded_objs < len(names):
        fails.append(f"{len(names)} fonts referenced but only {embedded_objs} embedded")
    unsubsetted = sorted({b.decode("latin-1") for b in base if b"+" not in b})
    if unsubsetted:
        notes.append(f"not subset-tagged (check these are embedded): {unsubsetted}")

    # --- page numbers, headers, footers ---------------------------------------------------
    pat = re.compile(rb"([\d.]+)\s+([\d.]+)\s+Td[^()]{0,200}?\((.{1,40}?)\)\s*Tj", re.S)
    low, high = set(), set()
    for s in content_streams(streams):
        for m in pat.finditer(s):
            y, t = float(m.group(2)), m.group(3).decode("latin-1").strip()
            if not t:
                continue
            if y < 90:
                low.add(t[:40])
            elif y > 750:
                high.add(t[:40])
    print(f"  footer-zone text      : {sorted(low) if low else 'none'}")
    print(f"  header-zone text      : {sorted(high) if high else 'none'}")
    if low:
        fails.append(f"text in the footer zone: {sorted(low)[:4]}")
    if high:
        fails.append(f"text in the header zone: {sorted(high)[:4]}")

    # --- placeholders and unresolved references in the RENDERED text -----------------------
    text = page_text(streams)
    placeholders = re.findall(r"TBD:?\s*([A-Za-z][A-Za-z ,]{0,28})", text)
    print(f"  TBD placeholders      : {placeholders if placeholders else 'none'}")
    if "TBD" in text:
        fails.append(f"TBD renders in the manuscript: {placeholders or 'label not recovered'}")
    if "??" in text:
        fails.append("an unresolved reference renders as ??")

    # --- what the log says ----------------------------------------------------------------
    if LOG.exists():
        log = LOG.read_text(encoding="utf-8", errors="replace")
        over = len(re.findall(r"Overfull \\[hv]box", log))
        undef = len(re.findall(r"(?i)undefined (reference|citation)", log))
        print(f"  overfull boxes        : {over}")
        print(f"  undefined refs/cites  : {undef}")
        if over:
            fails.append(f"{over} overfull box(es)")
        if undef:
            fails.append(f"{undef} undefined reference(s) or citation(s)")

    ver = re.match(rb"%PDF-(\d\.\d)", raw)
    print(f"  PDF version           : {ver.group(1).decode() if ver else '?'}")
    print(f"  size                  : {len(raw):,} bytes")

    for n in notes:
        print(f"  NOTE: {n}")
    print()
    if fails:
        print("NOT READY TO UPLOAD")
        for f in fails:
            print(f"  - {f}")
        return 1
    print("PDF is uploadable: within the page limit, A4, fonts embedded, no page numbers, "
          "headers, footers or placeholders")
    return 0


if __name__ == "__main__":
    sys.exit(main())
