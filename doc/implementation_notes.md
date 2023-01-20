# Implementation notes

This document explains some miscellaneous parts of the implementation of BAPCtools that did not fit in the [Subcommand documentation](commands.md).

# Extensions of problem format

## `@EXPECTED_RESULTS@: `
Submissions may contain the string `@EXPECTED_RESULTS@: ` anywhere in their source to indicate which verdicts are allowed for this submission.

- The final verdict of the submission must be in this list.
- Each testcase must either be accepted or have a verdict in this list. (This is to prevent issues with lazy judging/changing verdict priorities where the first non accepted testcase will be the final verdict.)


The `@EXPECTED_RESULTS@: ` tag should be followed by a comma separated list of verdicts from

- `ACCEPTED`,
- `WRONG_ANSWER`,
- `TIME_LIMIT_EXCEEDED`,
- `RUN_TIME_ERROR`.

Additionally, the following DOMjudge equivalents may be used:
- `CORRECT`,
- `WRONG-ANSWER` / `NO-OUTPUT`,
- `TIMELIMIT`,
- `RUN-ERROR`,
- `CHECK-MANUALLY`: this is not supported and will be ignored,
- `COMPILER-ERROR`: this is not supported and will be ignored.


Matching is case insensitive and extra white space is allowed. Examples:
- `// @EXPECTED_RESULTS@: WRONG_ANSWER`
- `# @expected_results@: accepted,time_limit_exceeded, no-output`

## Non-standard `generators.yaml` keys

The following non-standard top-level `generators/generators.yaml` keys are supported:
- `gitignore_generatred` (default `False`): Can be used to automatically write a `data/.gitignore` containing a single gitignore line like `secret/testcase.*` for each generated testcase.
  This file should not be modified manually as it will be overwritten each time testcases are regenerated.

# Building and running in tmpfs

For efficiency, BAPCtools tries to minimize the number of disk writes. This means that it will do as many things as possible in RAM. In practice, `tmpfs` (temporary file system in RAM) is used for this.
* On Linux, this is typically `/tmp/bapctools_6dhash/`, with one temporary directory per contest.
* On Windows, this may be `c:\temp\bapctools_6dhash\`.

From here on, let `~tmp` be the root temporary directory, e.g. `/tmp/bapctools_6dhash/`.
`~tmp` contains a directory structure that tries to mirror the directory structure of the problem archive itself.
Each 'program' (submission/validator/generator/visualizer) gets its own directory, as do testcases and runs:

- `~tmp/<contestname>/`: Used for compiling the contest pdf and solution slides. See the section on building LaTeX.
- `~tmp/<problemname>/`: Contains tex files to build the problem pdf. See the section on building LaTeX.
- `~tmp/<problemname>/{input,output}_validators/`: contains the build artefacts for all validators.
- `~tmp/<problemname>/submissions/<verdict>/<submission>/`: contains the build artefacts for all submissions.
- `~tmp/<problemname>/generators/<generator>/`: contains the build artefacts for all generators.
- `~tmp/<problemname>/data/(<group>/)*<testcase>/`: is used to generated the testcase and store metadata about it.
- `~tmp/<problemname>/data/(<group>/)*<testcase>.feedbackdir/`: contains the result of the input/output format validators.
- `~tmp/<problemname>/runs/<verdict>/<submission>/(<group>/)*<testcase>.out`: the output of the submission on the testcase.
- `~tmp/<problemname>/runs/<verdict>/<submission>/(<group>/)*<testcase>.feedbackdir`: the output validator feedback when validating the corresponding `.out`.

## Building programs

Each program (submission/validator/generator/visualizer) is build in its own directory (`~tmp/problemname/submissions/accepted/submission/`, from here on `~build`). Compilation is only done if either the sources or the compile command changed.

1. Detect the program language. Language detection rules are described in [languages.yaml](../config/languages.yaml).
1. Symlink all input files to `~build`. This can be either the single submission file, or all files/directories directly contained in the submission.
1. Find the `build` and `run` command for the current language.
1. If `~build/meta_` is newer than the last modification to any source file and contains exactly the `build` command, the build is up to date and nothing needs to be done.
1. Else, run the `build` command and update `~build/meta_` with this.
1. For compiled languages, we now (usually) have a file `~build/run` that is used as `{binary}` in the substitution of the `run` command. For interpreted languages, e.g. Python, the main file is given as `{mainfile}`.

## Generating testcases

Testcases are generated inside `~tmp/<problemname>/data/(<group>/)*<testcase>/` (from now on `~testcase`).
Testcases are only re-generated when changes were made. This is done with the following steps:

1. Check if the current data in `~testcase/meta_.yaml` is up to date. A testcase is up to date when all of the following hold:
    - `~testcase/meta_.yaml` must exist
    - `testcase.in` and `testcase.ans` must exist.
    - `~testcase/meta_.yaml` must be newer than the last modification to
        - the generator (or testcase source for manual cases)
        - the solution
        - the visualizer
        - the `testcase.in` file
        - the `testcase.ans` file.
    - the current generator invocation, solution invocation, and visualizer invocation must match the invocations stored in `~testcase/meta_.yaml`.
1. For manual testcases, symlink the given file to `~testcase/<testcase>.in`
1. For other cases, run the given generator with current working directory `~testcase`.
1. Validate the generated `~testcase/<testcase>.in` file.
1. If `~testcase/<testcase>.ans` was not generated and a solution was provided, run the solution with working directory `~testcase` to generate `~testcase/<testcase>.ans`.
    - For interactive problems, create an empty `~testcase/<testcase>.ans` and run the given submission to create a `~testcase/<testcase>.interaction`.
1. Validate the generated `~testcase/<testcase>.ans` file.
1. If provided, run the visualizer with working directory `~testcase`.
1. Copy generated files to the `data/` directory. For changed files, `--force` is needed to overwrite them.
1. Update the `~testcase/meta_.yaml` file with the invocations of the generator, solution, and visualizer.

# Building LaTeX files

## Problem statement pdfs

### Per-problem pdf

The per-problem pdfs are created inside `<tmpdir>/<problemname>`:

* `~tmp/<problemname>/problem_statement/`: a symlink to the `problem_statement/` directory.
* `~tmp/<problemname>/samples.tex`: a generated table containing the sample cases.
* `~tmp/<problemname>/bapc.cls`: a symlink to the latex class.
* `~tmp/<problemname>/problem.tex`: a wrapper to compile the problem statement and samples into a pdf.

The statement is compiled using:
```
latexmk -cd -g -pdf -pdflatex='pdflatex -interaction=nonstopmode -halt-on-error' [-pvc] [-e $max_repeat=1] -output-directory=~tmpdir/<problemname> ~tmpdir/<problemname>/problem.tex
```

The `-pvc` option is only passed to `latexmk` when `--watch` is passed to BAPCtools.
The `-e $max_repeat=1` option is only passed to `latexmk` when `-1` is passed to BAPCtools.

### Full contest pdf

After creating the `samples.tex` for each problem, the contest pdf is created in `~tmpdir/<contestname>` like this:

* `~tmp/<contestname>/contest_data.tex`: a filled in copy of [contest_data.tex](../latex/contest-data.tex) containing the name, subtitle, year, and authors of the contest.
* `~tmp/<contestname>/bapc.cls`: a symlink to the latex class.
* `~tmp/<contestname>/logo.{pdf,png,jpg}`: a symlink to the contest logo provided in the contest directory or the one above.
* `~tmp/<contestname>/contest-problems.tex`: filled in copies of [contest-problem.tex](../latex/contest-problem.tex) containing the files to include for each problem.
* `~tmp/<contestname>/contest[-web].tex`: a wrapper to compile the contest. This includes `contest_data.tex` and `contest-problems.tex`.

The statement is compiled using:

```
latexmk -cd -g -pdf -pdflatex='pdflatex -interaction=nonstopmode -halt-on-error' [-pvc] [-e $max_repeat=1] -output-directory=~tmpdir/<contestname> ~tmpdir/<problemname>/contest[-web].tex
```

## Solution slides

Solutions are rendered in a similar way to the contest pdf. It uses the `problem_statement/solution.tex` files as inputs. The main difference is the additional inclusion of

- `solutions_header.tex`: slides prepended to the first problem.
- `solutions_footer.tex`: slides appended after the last problem.

### Solve stats

There is some special support for handling _solve stats_: post-contest data on how often each problem was solved. To use this, create the following directory layout in your contest directory.

- `<contest>/solve_stats/problem_stats.tex`: Contains one line for each problem label:
  ```
  \newcommand{\solvestatsA}{\printsolvestats{<number submissions>}{<number accepted>}{<number unknown>}}
  ```
  When this file is present, each `problem_statement/solution.tex` may use `\solvestats` to print a line like:
  ```
  Statistics: 15 submissions, 3 accepted, 8 unknown
  ```
- `<contest>/solve_stats/language_stats.pdf`: a plot of the language distribution of all submissions. This may be included directly by the `solution_header.tex` or `solution_footer.tex`. (BAPCtools doesn't do anything special here.)

- `<contest>/solve_stats/activity/<label>.pdf`: One file per problem, containing a plot of the submissions over time. These will automatically be included on the solution slides for each problem when available.

All the files in the `<contest>/solve_stats` directory can be generated using `bt solve_stats`. More details [here](commands.md#solve_stats).

# Constraints checking

Validators based on [headers/validation.h](../headers/validation.h) can take a `--constraints_file <file_path>` flag.
After validation is done, the validator will write a file to the given path containing the minimum and maximum values seen for all numbers read in the input or output. Each line in the output file will look like:
```
<source_location> <bool reached minimum> <bool reached maximum> <minimum allowed> <maximum allowed> <minimum seen> <maximum seen>
```

For example, the code `v.read_integer("a", 1, 1000)` on line `7` could generate the line:
```
/tmp/bapctools_abcdef/findmyfamily/input_validators/input_validator/input_validator.cpp:7 0 0 999 999 1 1000
```

Everything up to and including `:7` is the file and line of the `read_integer` statement. The two zeros indicate that the minimum and maximum value were not reached (i.e. boolean false). The `999 999` indicate that `a` was read, and the smallest and largest value of `a` we encountered was `999`. The final `1 1000` indicate the valid range of `a`.

BAPCtools will accumulate these values over all testcases, and print a warning when the minimum or maximum value of a `read` statement was never reached.

This system works for any validator that accepts the `--constraints_file` flag. This is determined by searching all sources for `constraints_file`.

Note: `validation.h` requires `std::source_location`, which is available since C++20. BAPCtools will automatically add this as an additional C++ flag when needed. This may not work on systems not supporting C++20.

The following regexes are used to extract bounds from the problem statement:
- `{\\(\w+)}{(.*)}`: `\newcommand{\maxa}{1000}`
- `([0-9-e,.^]+)\s*(?:\\leq|\\geq|\\le|\\ge|<|>|=)\s*(\w*)`: `0 \leq a`
- `(\w*)\s*(?:\\leq|\\geq|\\le|\\ge|<|>|=)\s*([0-9-e,.^]+)`: `a < 10^9`
