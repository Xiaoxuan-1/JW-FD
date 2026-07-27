# JW-FD SPIE Proceedings Paper

LaTeX source for the SPIE conference manuscript describing the JW-FD multimodal solar flare forecasting dataset.

## Build

Requires a TeX distribution with `pdflatex`, `bibtex`, and packages: `graphicx`, `amsmath`, `booktabs`, `tikz` (with `positioning`, `arrows.meta`, `shapes.geometric`).

```bash
cd paper
make
```

Output: `main.pdf` (target: **6 pages**, SPIE Proceedings format)

The expanded manuscript includes Related Work, detailed pipeline methodology, configuration and feature tables, label-window figure, multimodal alignment section, and evaluation-protocol discussion.

**Overleaf (recommended if local TeX is unavailable):** Upload the entire `paper/` folder to [Overleaf SPIE template](https://www.overleaf.com/latex/templates/spie-proceedings-style-template-and-guidelines-for-authors/qpkhfttzvnhz), replace the body with `main.tex`, and set the main document to `main.tex`. Compile with pdfLaTeX + BibTeX.

Estimated length: ~2,750 words of prose plus 6 tables and 2 figures $\approx$ 6 SPIE pages at 10pt single column.

Manual build:

```bash
pdflatex main
bibtex main
pdflatex main
pdflatex main
```

## SPIE submission notes

- Uses official `spie.cls` and `spiebib.bst` (included in this directory).
- Target length: 6 pages (minimum for some SPIE conferences).
- Embed all fonts in the final PDF before submission.
- Overleaf: upload this folder or use the [SPIE Proceedings template](https://www.overleaf.com/latex/templates/spie-proceedings-style-template-and-guidelines-for-authors/qpkhfttzvnhz) and copy `main.tex` content.

## Files

| File | Description |
|------|-------------|
| `main.tex` | Manuscript |
| `references.bib` | Bibliography |
| `figures/pipeline.tex` | TikZ pipeline diagram |
| `spie.cls` / `spiebib.bst` | SPIE style files |
