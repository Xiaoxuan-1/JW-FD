# JW-FD SPIE Proceedings Paper

**Status: published. Manuscript frozen — do not edit.**

Recorded 2026-09-01. This proceedings paper is out; author-side revisions are closed.

**Canonical final version:** last edits were done on **中国科技云 Overleaf** ([https://latex.cstcloud.cn](https://latex.cstcloud.cn)). That Overleaf project is the author-of-record source that was submitted/published. Files under `paper/SPIE/` in this repo are a local snapshot and **may lag** the Overleaf final; do not treat them as the camera-ready copy, and do not sync local changes back as if they were the published text.

Do not change `main.tex`, `references.bib`, figures, style files, or rebuild the PDF for content edits unless the authors explicitly request an erratum. Ongoing JW-FD journal work belongs in `paper/universe/` (MDPI *Universe*), not here.

## Publication

| Item | Value |
|------|--------|
| Title | An end-to-end pipeline for multimodal solar flare forecasting dataset construction |
| Authors | Shao Mingfu, Lin Jiaben, Wang Hui, Tong Liyue, Li Yuyang |
| Venue | SPIE Astronomical Telescopes + Instrumentation 2026, Copenhagen, 5–10 July 2026 |
| Proceedings | Proc. SPIE **14155**, Software and Cyberinfrastructure for Astronomy IX |
| Paper ID | **14155-94** |
| Final source | 中国科技云 Overleaf（[latex.cstcloud.cn](https://latex.cstcloud.cn)）— last edits and canonical author files |
| Local snapshot | `main.pdf` / TeX in this directory (not guaranteed identical to Overleaf) |

Suggested citation (fill in the official DOI from the SPIE Digital Library if needed):

```bibtex
@inproceedings{Shao2026jwfdspie,
  author    = {Shao, Mingfu and Lin, Jiaben and Wang, Hui and Tong, Liyue and Li, Yuyang},
  title     = {An end-to-end pipeline for multimodal solar flare forecasting dataset construction},
  booktitle = {Software and Cyberinfrastructure for Astronomy IX},
  series    = {Proc. SPIE},
  volume    = {14155},
  number    = {14155-94},
  year      = {2026},
  address   = {Copenhagen, Denmark}
}
```

## Build (archival only)

Requires a TeX distribution with `pdflatex`, `bibtex`, and packages: `graphicx`, `amsmath`, `booktabs`, `tikz` (with `positioning`, `arrows.meta`, `shapes.geometric`).

```bash
cd paper/SPIE
make
```

Output: `main.pdf` (SPIE Proceedings format, ~6 pages).

Manual build:

```bash
pdflatex main
bibtex main
pdflatex main
pdflatex main
```

## Files

| File | Description |
|------|-------------|
| `main.tex` | Frozen manuscript |
| `references.bib` | Frozen bibliography |
| `figures/pipeline.tex` | TikZ pipeline diagram |
| `figures/label_timeline.tex` | Label-window figure |
| `spie.cls` / `spiebib.bst` | SPIE style files |
| `SPIE_Poster_shaomf.pdf` | Conference poster |
| `doi_examples/` | Reference PDFs used during DOI-link checks |
