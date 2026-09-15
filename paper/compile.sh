#!/bin/sh
# Real compile, in a container, because there is no TeX on the authoring machine.
#
# paper/estimate_pages.py is a WORD MODEL and it was wrong by nearly a full page: it said
# 6.06 of 6 while pdflatex produced 7. Its own docstring claimed +/- 0.2. Treat it as a
# rough guide for cutting between compiles and nothing more; this script is the arbiter.
#
#   sh paper/compile.sh
#
# Needs Docker and the texlive/texlive image. On Git Bash, MSYS_NO_PATHCONV=1 stops the
# shell rewriting /w into a Windows drive path.
set -e
REPO=$(cd "$(dirname "$0")/.." && pwd)
MSYS_NO_PATHCONV=1 docker run --rm -v "$REPO/paper:/w" -w /w texlive/texlive:latest sh -c '
  pdflatex -interaction=nonstopmode -halt-on-error main.tex >/dev/null 2>&1 || {
    echo "FIRST PASS FAILED"; tail -40 main.log; exit 1; }
  bibtex main >/dev/null 2>&1
  pdflatex -interaction=nonstopmode main.tex >/dev/null 2>&1
  pdflatex -interaction=nonstopmode main.tex >/dev/null 2>&1
  grep -E "Output written" main.log
  echo "--- overfull boxes ---"
  grep -c "Overfull" main.log || true
  grep "Overfull" main.log | head -5 || true
  echo "--- undefined refs / citations ---"
  grep -iE "undefined (reference|citation)|multiply defined" main.log | head -5 || echo "none"
'
