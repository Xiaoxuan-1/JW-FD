# JW-FD Universe (MDPI) Data Descriptor paper
MAIN = jwfd
LATEX = pdflatex
BIBTEX = bibtex

.PHONY: all clean view

all: $(MAIN).pdf

$(MAIN).pdf: $(MAIN).tex references.bib figures/*.tex Definitions/mdpi.cls
	$(LATEX) $(MAIN)
	$(BIBTEX) $(MAIN)
	$(LATEX) $(MAIN)
	$(LATEX) $(MAIN)

clean:
	rm -f $(MAIN).aux $(MAIN).bbl $(MAIN).blg $(MAIN).log $(MAIN).out $(MAIN).pdf

view: $(MAIN).pdf
	@echo "Open $(MAIN).pdf with your PDF viewer."
