"""Produce the file to upload, and refuse to produce it while the PDF is not uploadable.

WHY IT IS NOT JUST `cp`. main.pdf is a build artifact: compile.sh writes it, check_pdf.py and
check_numbers.py read it by that name, and renaming it in the repository breaks all three. The
upload needs a different name for two reasons:

  * "main.pdf" is nobody's paper. It arrives in a reviewer's downloads beside a dozen others.
  * THE BLIND POLICY IS UNRESOLVED, so the filename must not identify the author. This is the
    step people forget after carefully anonymising the author block -- and then upload
    Surname2026.pdf. The name below contains no name, no institution and no city.

The copy is gated on check_pdf.py, so a PDF with a placeholder still rendering, a seventh page,
a missing font or a page number cannot become the file you drag into EDAS. That is the whole
point: the rename is the last step, and the last step is where a bad build gets shipped.

    python paper/make_upload_copy.py
    python paper/make_upload_copy.py --name RIVF2026-something-else.pdf
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PDF = HERE / "main.pdf"
DEFAULT_NAME = "RIVF2026-attribution-coverage-audit.pdf"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default=DEFAULT_NAME,
                    help=f"filename for the upload copy (default: {DEFAULT_NAME})")
    ap.add_argument("--force", action="store_true",
                    help="copy even if check_pdf.py fails; you are on your own")
    a = ap.parse_args()

    if not PDF.exists():
        print("main.pdf does not exist -- run `sh paper/compile.sh` first")
        return 1

    gate = subprocess.run([sys.executable, str(HERE / "check_pdf.py")],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(gate.stdout.rstrip())

    if gate.returncode != 0 and not a.force:
        print("\nNO COPY MADE. The PDF is not uploadable; fix the above and run this again.")
        print("If you know better, re-run with --force.")
        return 1

    # a filename that names a person defeats the anonymisation it sits beside
    lowered = a.name.lower()
    for leak in ("nguyen", "son", "utc", "hanoi", "giao thong"):
        if leak in lowered:
            print(f"\nREFUSED: the filename contains {leak!r}. The blind policy is unresolved, "
                  f"so the upload filename must not identify the author or the institution.")
            return 1

    dest = HERE / a.name
    shutil.copy2(PDF, dest)
    digest = hashlib.sha256(dest.read_bytes()).hexdigest()
    same = digest == hashlib.sha256(PDF.read_bytes()).hexdigest()

    print(f"\nupload copy : {dest}")
    print(f"bytes       : {dest.stat().st_size:,}")
    print(f"sha256      : {digest}")
    print(f"identical to main.pdf: {same}")
    if a.force and gate.returncode != 0:
        print("\nMADE WITH --force WHILE THE GATE WAS RED. Do not upload this without reading "
              "the failures above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
