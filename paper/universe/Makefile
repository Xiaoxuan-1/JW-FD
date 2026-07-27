# JW-FD Universe (MDPI) Data Descriptor paper
MAIN = jwfd
LATEX = pdflatex -interaction=nonstopmode -halt-on-error
BIBTEX = bibtex

.PHONY: all clean view cover_letter

all: $(MAIN).pdf

$(MAIN).pdf: $(MAIN).tex references.bib figures/*.tex Definitions/mdpi.cls
	$(LATEX) $(MAIN)
	-$(BIBTEX) $(MAIN)
	$(LATEX) $(MAIN)
	$(LATEX) $(MAIN)

cover_letter: cover_letter.pdf

cover_letter.pdf: cover_letter.tex
	$(LATEX) cover_letter

clean:
	rm -f $(MAIN).aux $(MAIN).bbl $(MAIN).blg $(MAIN).log $(MAIN).out $(MAIN).pdf
	rm -f cover_letter.aux cover_letter.log cover_letter.out cover_letter.pdf

view: $(MAIN).pdf
	@echo "Open $(MAIN).pdf with your PDF viewer."
