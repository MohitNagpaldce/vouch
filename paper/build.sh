#!/bin/bash
# Build paper.pdf (and paper.tex) from paper.md.
# Requires: pandoc, tectonic.
set -e
cd "$(dirname "$0")"

# Default LaTeX fonts lack some Unicode glyphs; map them for the PDF only so
# paper.md stays clean for GitHub rendering.
SRC=$(mktemp -t vouchpaper).md
sed -e 's/≈/~/g' \
    -e 's/≥/>=/g' \
    -e 's/≤/<=/g' \
    -e 's/≠/!=/g' \
    -e 's/−/-/g' \
    -e 's/→/->/g' \
    -e 's/×/x/g' \
    -e 's/⏳ //g' \
    paper.md | tail -n +10 > "$SRC"   # drop the md title block; metadata supplies it
trap 'rm -f "$SRC"' EXIT

COMMON=(
  "$SRC"
  --from=markdown+tex_math_dollars+pipe_tables+footnotes
  --standalone
  --resource-path=.
  -V documentclass=article
  -V papersize=letter
  -V fontsize=10pt
  -V geometry:margin=1in
  -V linkcolor=blue
  -V urlcolor=blue
  -V colorlinks=true
  --metadata title="Vouch: A Verification Gate for AI-Generated Code, with Portable Evidence Attestations"
  --metadata author="Mohit Nagpal, Independent Researcher (mht.nagpal@gmail.com)"
  --metadata date="$(date +%Y-%m-%d)"
)

pandoc "${COMMON[@]}" -o paper.tex
pandoc "${COMMON[@]}" --pdf-engine=tectonic -o paper.pdf
echo "built: $(pwd)/paper.pdf and paper.tex"
