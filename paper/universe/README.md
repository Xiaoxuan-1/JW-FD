# JW-FD Universe Data Descriptor Paper

MDPI **Universe** journal manuscript (`datadescriptor` article type) describing the JW-FD multimodal solar flare forecasting dataset (2011–2025).

## Files

| File | Description |
|------|-------------|
| `jwfd.tex` | Main manuscript |
| `references.bib` | Bibliography |
| `figures/` | TikZ figures (pipeline, label timeline, yearly chart) |
| `Definitions/` | MDPI LaTeX class (from `Universe.zip`) |
| `template.tex` | Pristine MDPI template (reference only) |

## Build

```bash
cd paper/universe
make
```

Or manually:

```bash
pdflatex jwfd
bibtex jwfd
pdflatex jwfd
pdflatex jwfd
```

Requires a TeX distribution with `pdflatex`, `bibtex`, `pgfplots`, and TikZ.

**Note:** Local compilation may fail if the conda `texlive-core` installation is incomplete (missing `pdflatex.fmt`). In that case, upload `jwfd.tex`, `references.bib`, `figures/`, and `Definitions/` to [Overleaf](https://www.overleaf.com) using the MDPI Universe template as base, or install a full TeX Live distribution system-wide.

## Dataset statistics (2011–2025)

- 3,064 active regions
- 1,991,247 magnetogram snapshots
- 3,064 MP4 evolution videos
- 12,298 NOAA flare label records
- Train/val/test: 2,450 / 307 / 307 ARs (80/10/10, seed 62)

Source: `/data/Datasets/JW-FD/`

## Related

- Pipeline repo: https://github.com/Xiaoxuan-1/JW-FD
- SPIE conference paper (pipeline methods): `../SPIE/main.tex`
