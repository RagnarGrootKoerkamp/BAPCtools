# The problem statement files should be in problems/[problem]/statement/statement.tex.
# If this file is not present, the problem will be ignored!
# The main purpose of having this in a subdirectory is to not clutter up
# the problem directory with images.

# useful commands:
# `make problems`
# `make bapc`
# `make preliminaries`
# `make problems/[problem]/statement.pdf`
# `make 1` to make problem number 1

# some variables that might be changed
CONTESTS := preliminaries bapc preliminaries_testsession bapc_testsession
PROBLEM_DIRECTORY := problems
TEX_PATH := statement/statement.tex
SOLUTION_TEX_PATH := statement/solution.tex
STATEMENT_PATH := statement.pdf
SOLUTION_PATH := solution.pdf
CONTEST_PDF := problems.pdf
CONTEST_SOLUTION := solutions.pdf
SAMPLE_DIRECTORY := data/sample

COPY_PDF := ln -sf

# latex settings
LATEX_DIRECTORY := latex
TEMPLATE := template.tex
SOLUTION_TEMPLATE := template_solution.tex
# symlink this to somewhere in tmpfs for faster builds :)
BUILD_DIRECTORY := .build
INPUT_FILE := .build/input.tex
INPUT_FILE_TEMPLATE := input.tex.template

# internal variables
TEX_PATHS := $(wildcard $(PROBLEM_DIRECTORY)/*/$(TEX_PATH))
PROBLEMS := $(TEX_PATHS:/$(TEX_PATH)=)
STATEMENT_PATHS := $(PROBLEMS:%=%/$(STATEMENT_PATH))
SOLUTION_PATHS := $(PROBLEMS:%=%/$(SOLUTION_PATH))
ROOT_DIR_FROM_LATEX := ..
DEPENDENCY_FILE := .dependencies
SAMPLE_PATHS := $(PROBLEMS:$(PROBLEM_DIRECTORY)/%=$(LATEX_DIRECTORY)/$(BUILD_DIRECTORY)/%.sample)

# some targets
all: problems contests
contests: $(CONTESTS)
problems: $(STATEMENT_PATHS)
$(CONTESTS) : % : %/$(CONTEST_PDF) %/$(CONTEST_SOLUTION)

# problem number targets
$(DEPENDENCY_FILE) : $(PROBLEMS)
	#@echo $^ | sed 's#\(problems/\([0-9]\+\)_[^ ]*\)[^ ]* \?#\2: \1/$(STATEMENT_PATH) \1/$(SOLUTION_PATH)\n#g' > $(DEPENDENCY_FILE)

include $(DEPENDENCY_FILE)

.PHONY : all contests bapc preliminaries problems echo clean links update_problems builddir $(CONTESTS)

update_problems: links
	rm $(DEPENDENCY_FILE)


links:
	@$(foreach contest,$(CONTESTS),\
		$(foreach problem,$(wildcard $(contest)/*/), \
			ln -sfn ../$(problem) $(PROBLEM_DIRECTORY)/ ; \
		) \
	)
	#remove broken links
	find -L $(PROBLEM_DIRECTORY) -maxdepth 1 -type l -delete

clean:
	rm -rf $(LATEX_DIRECTORY)/$(BUILD_DIRECTORY)/*
	rm -f $(DEPENDENCY_FILE)

echo:
	@echo problems: $(PROBLEMS)
	@echo problem numbers: $(PROBLEM_NUMBERS)
	@echo tex paths: $(TEX_PATHS)
	@echo pdf paths: $(STATEMENT_PATHS)
	@echo solution paths: $(SOLUTION_PATHS)
	@echo sample paths: $(SAMPLE_PATHS)

builddir : $(LATEX_DIRECTORY)/$(BUILD_DIRECTORY)

$(LATEX_DIRECTORY)/$(BUILD_DIRECTORY) :
	@mkdir -p $(LATEX_DIRECTORY)/$(BUILD_DIRECTORY)


# sample target
.SECONDEXPANSION:
$(SAMPLE_PATHS): $(LATEX_DIRECTORY)/$(BUILD_DIRECTORY)/%.sample : $$(sort $$(wildcard $$(PROBLEM_DIRECTORY)/%/$$(SAMPLE_DIRECTORY)/*.in))
	@cat /dev/null > $@
	@$(foreach sample, $^, \
		printf '\\begin{Sample}\n' >> $@ ; \
		sed 's/$$/\\newline/;$$ s/\\newline//' $(sample) >> $@ ; \
		printf '&\n' >> $@ ; \
		sed 's/$$/\\newline/;$$ s/\\newline//' $(sample:%.in=%.ans) >> $@ ; \
		printf '\\\\\n' >> $@ ; \
		printf '\\end{Sample}\n\n' >> $@ ; \
	)

# build problem pdfs
$(STATEMENT_PATHS): $(PROBLEM_DIRECTORY)/%/$(STATEMENT_PATH) : $(PROBLEM_DIRECTORY)/%/$(TEX_PATH) $(LATEX_DIRECTORY)/$(BUILD_DIRECTORY)/%.sample
	@sed -e 's#__DIR__#$(ROOT_DIR_FROM_LATEX)/$(dir $<)#' \
		-e 's#__FILE__#$(ROOT_DIR_FROM_LATEX)/$<#' \
		-e 's#__SAMPLE__#$(BUILD_DIRECTORY)/$*.sample#' \
		< $(LATEX_DIRECTORY)/$(INPUT_FILE_TEMPLATE) \
		> $(LATEX_DIRECTORY)/$(INPUT_FILE)
	@cd $(LATEX_DIRECTORY) && pdflatex -jobname $* -output-directory $(BUILD_DIRECTORY) $(TEMPLATE)
	@rm $(LATEX_DIRECTORY)/$(INPUT_FILE)
	$(COPY_PDF) ../../$(LATEX_DIRECTORY)/$(BUILD_DIRECTORY)/$*.pdf $@

# build problem solution slide
$(SOLUTION_PATHS): $(PROBLEM_DIRECTORY)/%/$(SOLUTION_PATH) : $(PROBLEM_DIRECTORY)/%/$(SOLUTION_TEX_PATH)
	@echo "input{$(ROOT_DIR_FROM_LATEX)/$<}" > $(LATEX_DIRECTORY)/$(INPUT_FILE)
	@sed -e 's#__DIR__#$(ROOT_DIR_FROM_LATEX)/$(dir $<)#' \
		-e 's#__FILE__#$(ROOT_DIR_FROM_LATEX)/$<#' \
		-e '/__SAMPLE__/d' \
		< $(LATEX_DIRECTORY)/$(INPUT_FILE_TEMPLATE) \
		> $(LATEX_DIRECTORY)/$(INPUT_FILE)
	cd $(LATEX_DIRECTORY) && pdflatex -jobname $*-solution -output-directory $(BUILD_DIRECTORY) $(SOLUTION_TEMPLATE)
	@rm $(LATEX_DIRECTORY)/$(INPUT_FILE)
	$(COPY_PDF) ../../$(LATEX_DIRECTORY)/$(BUILD_DIRECTORY)/$*.pdf $@

# build the contest pdf
%/$(CONTEST_PDF): $$(wildcard %/*/$(TEX_PATH)) $(SAMPLE_PATHS)
	@echo > $(LATEX_DIRECTORY)/$(INPUT_FILE)
	@# sort problems alphabetical
	$(eval PROBLEMS := $(shell ./tools/tools.py -c $* sort))
	@$(foreach problem, $(PROBLEMS), \
		echo "PROBLEM: " $(problem) && \
		sed -e 's#__DIR__#$(ROOT_DIR_FROM_LATEX)/$(problem)$(dir $(TEX_PATH))#' \
			-e 's#__FILE__#$(ROOT_DIR_FROM_LATEX)/$(problem)$(TEX_PATH)#' \
			-e 's#__SAMPLE__#$(BUILD_DIRECTORY)/$(notdir $(problem:%/=%)).sample#' \
		< $(LATEX_DIRECTORY)/$(INPUT_FILE_TEMPLATE) \
		>> $(LATEX_DIRECTORY)/$(INPUT_FILE); \
	)
	# three runs, for TOC to work
	@cd $(LATEX_DIRECTORY) && pdflatex -output-directory $(BUILD_DIRECTORY) $*.tex
	@cd $(LATEX_DIRECTORY) && pdflatex -output-directory $(BUILD_DIRECTORY) $*.tex > /dev/null
	@cd $(LATEX_DIRECTORY) && pdflatex -output-directory $(BUILD_DIRECTORY) $*.tex > /dev/null
	@rm $(LATEX_DIRECTORY)/$(INPUT_FILE)
	$(COPY_PDF) ../$(LATEX_DIRECTORY)/$(BUILD_DIRECTORY)/$*.pdf $@

# build contest solutions
%/$(CONTEST_SOLUTION): $$(wildcard %/*/$(SOLUTION_TEX_PATH))
	@echo > $(LATEX_DIRECTORY)/$(INPUT_FILE)
	@# sort problems alphabetical
	$(eval PROBLEMS := $(shell ./tools/tools.py -c $* sort))
	@$(foreach problem, $(PROBLEMS), \
		echo "PROBLEM: " $(problem) && \
		test -f "$(problem)$(SOLUTION_TEX_PATH)" && \
		sed -e 's#__DIR__#$(ROOT_DIR_FROM_LATEX)/$(problem)$(dir $(SOLUTION_TEX_PATH))#' \
			-e 's#__FILE__#$(ROOT_DIR_FROM_LATEX)/$(problem)$(SOLUTION_TEX_PATH)#' \
			-e '/__SAMPLE__/d' \
		< $(LATEX_DIRECTORY)/$(INPUT_FILE_TEMPLATE) \
		>> $(LATEX_DIRECTORY)/$(INPUT_FILE) \
		|| echo skipped ; \
	)
	echo hoi
	# three runs, for TOC to work
	cd $(LATEX_DIRECTORY) && pdflatex -output-directory $(BUILD_DIRECTORY) $*_solutions.tex
	@cd $(LATEX_DIRECTORY) && pdflatex -output-directory $(BUILD_DIRECTORY) $*_solutions.tex > /dev/null
	@cd $(LATEX_DIRECTORY) && pdflatex -output-directory $(BUILD_DIRECTORY) $*_solutions.tex > /dev/null
	@rm $(LATEX_DIRECTORY)/$(INPUT_FILE)
	$(COPY_PDF) ../$(LATEX_DIRECTORY)/$(BUILD_DIRECTORY)/$*_solutions.pdf $@
