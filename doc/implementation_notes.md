# Implementation notes

This document explains some miscellaneous parts of the implementation of BAPCtools that did not fit in the [Subcommand documentation](commands.md).

# Extensions of problem format

## `@EXPECTED_RESULTS@: `

Submissions with more than one allowed verdict must contain the string `@EXPECTED_RESULTS@: ` anywhere in their source to indicate which verdicts are allowed for this submission.

- The final verdict of the submission must be in this list.
- Each testcase must either be accepted or have a verdict in this list. (This is to prevent issues with lazy judging/changing verdict priorities where the first non-accepted testcase will be the final verdict.)

A submission with an `@EXPECTED_RESULTS@: ` tag should not be placed in one of the four [standard](https://icpc.io/problem-package-format/#submissions-correct-and-incorrect) submission directories, because [DOMjudge will ignore the tag](https://github.com/DOMjudge/domjudge/issues/1861) in this case. Directory names like `mixed/` or `rejected/` are typically used in this case.

The `@EXPECTED_RESULTS@: ` tag should be followed by a comma-separated list of verdicts from

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

Matching is case-insensitive and extra white space is allowed. Examples:

- `// @EXPECTED_RESULTS@: WRONG_ANSWER`
- `# @expected_results@:  accepted,time_limit_exceeded, no-output`

# Building and running in tmpfs

For efficiency, BAPCtools tries to minimize the number of disk writes. This means that it will do as many things as possible in RAM. In practice, `tmpfs` (temporary file system in RAM) is used for this.

- On Linux, this is typically `/tmp/bapctools_6dhash/`, with one temporary directory per contest.
- On Windows, this may be `c:\temp\bapctools_6dhash\`.

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

1. Check if the current data in `~testcase/meta_.yaml` is up to date.
1. Run the given generator with current working directory `~testcase/`.
1. For copied testcases, copy files to `~testcase/`
1. Write hardcoded files to`~testcase/`.
1. Validate the generated `~testcase/<testcase>.in` file.
1. If `~testcase/<testcase>.ans` was not generated and a solution was provided, run the solution with working directory `~testcase` to generate `~testcase/<testcase>.ans`.
   - For interactive problems, create an empty `~testcase/<testcase>.ans` and run the given submission to create a `~testcase/<testcase>.interaction`.
1. Validate the generated `~testcase/<testcase>.ans` file.
1. If provided, run the visualizer with working directory `~testcase/`.
1. Copy generated files to the `data/` directory. For changed files, `--force` is needed to overwrite them.
1. Update the `~testcase/meta_.yaml` file with the invocations of the generator,
   solution, and visualizer and hash of the `.in` file.

# Building LaTeX files

BAPCtools comes with a set of latex classes/headers to automatically render
problem, contest, and solution PDFs. These files are available in [`/latex/`](../latex).

To customize the style, you can provide your own modified copy of any of the
header files in `<contestdirectory>/` and they will be used instead of the
BACPtools provided files. For example, you can provide your own
`<contestdirectory>/contest.tex` as replacement entrypoint for building contest
PDFs. You can either manually include problems there, or use
`\input{./contest-problems.tex}` to include the automatically generated content.
This will instantiate the [`contest-problem.tex`](../latex/contest-problem.tex)
template once for each problem in the contest. This template itself can also be
modified if desired.

See also the docs on using multiple languages [here](./multiple_languages.md).

## Problem statement pdfs

### Per-problem pdf

The per-problem pdfs are created inside `<tmpdir>/<problemname>/latex/<language>`:

- `~tmp/<problemname>/latex/<language>/samples.tex`: a generated table containing the sample cases.
- `~tmp/<problemname>/latex/<language>/problem.tex`: a wrapper to compile the problem statement and samples into a pdf.

The statement is compiled using:

```
export TEXINPUTS=.;./solve_stats;./solve_stats/activity;~bapctools/latex;
latexmk -cd -g -usepretex="\newcommand\lang{<language>}" -pdf -pdflatex='pdflatex -interaction=nonstopmode -halt-on-error %O %P' [-pvc -view=none] [-e $max_repeat=1] ~tmpdir/<problemname>/latex/<language>/problem.tex
```

The `-pvc` option is only passed to `latexmk` when `--watch` is passed to BAPCtools.
The `-e $max_repeat=1` option is only passed to `latexmk` when `-1` is passed to BAPCtools.
The `\lang` macro can be used in any place to obtain the used language

The following placeholders are automatically substituted in the `problem.tex`:
```
{%problemlabel%}
{%problemyamlname%}
{%problemauthor%}
{%timelimit%}
{%problemdir%}
{%problemdirname%}
{%builddir%}
```

### Full contest pdf

After creating the `samples.tex` for each problem, the contest pdf is created in `~tmpdir/<contestname>` like this:

- `~tmp/<contestname>/latex/<language>/contest_data.tex`: a filled in copy of [contest_data.tex](../latex/contest-data.tex) containing the name, subtitle, year, and authors of the contest.
- `~tmp/<contestname>/latex/<language>/contest-problems.tex`: filled in copies of [contest-problem.tex](../latex/contest-problem.tex) containing the files to include for each problem.

The statement is compiled using:

```
export TEXINPUTS=.;./solve_stats;./solve_stats/activity;~bapctools/latex;
latexmk -cd -g -usepretex="\newcommand\lang{<language>}" -pdf -pdflatex='pdflatex -interaction=nonstopmode -halt-on-error %O %P' [-pvc -view=none] [-e $max_repeat=1] ~tmpdir/<contestname>/latex/<language>/contest[-web].tex
```

The `\lang` macro can be used in any place to obtain the used language

The following placeholders are automatically substituted in the `contest_data.tex`:
```
{%title%}
{%subtitle%}
{%year%}
{%author%}
{%testsession%}
{%logofile%}
...
<any entry in the contest.yaml>
```

## Solution slides

Solutions are rendered in a similar way to the contest pdf. It uses the
`problem_statement/solution.tex` files as inputs. The main difference is that
you can provide additional files in `<contestdirectory>/`:

- `solutions_header.xy.tex`: slides prepended to the first problem, for the
  current language.
- `solutions_footer.xy.tex`: slides appended after the last problem, for the
  current language.

The following placeholders are automatically substituted in the `solution.tex`:
```
{%problemlabel%}
{%problemyamlname%}
{%problemauthor%}
{%timelimit%}
{%problemdir%}
{%problemdirname%}
{%builddir%}
```

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

For constraints checking, BAPCtools passes the flag `--constraints_file <file_path>` to input, answer, and output validators.
After validation is done, the validator will write a file to the given path containing the minimum and maximum values seen for all numbers read in the input or output.
Each line in the output file will look like:

```
<string name> <string name> <bool reached minimum> <bool reached maximum> <minimum allowed> <maximum allowed> <minimum seen> <maximum seen>
```

For example, the code `v.read_integer("a", 1, 1000)` on line `7` could generate the line:

```
a a 0 0 999 999 1 1000
```

The two zeros indicate that the minimum and maximum value were not reached (i.e. boolean false). The `999 999` indicate that `a` was read, and the smallest and largest value of `a` we encountered was `999`. The final `1 1000` indicate the valid range of `a`.

BAPCtools will accumulate these values over all testcases, and print a warning when the minimum or maximum value of a `read` statement was never reached.

This system works for any validator that accepts the `--constraints_file` flag.
This is determined by searching all sources for the string `constraints_file`.
Validators based on [headers/validation.h](../headers/validation.h) accept this flag.

The following regexes are used to extract bounds from the problem statement:

- `{\\(\w+)}{(.*)}`: `\newcommand{\maxa}{1000}`
- `([0-9-e,.^]+)\s*(?:\\leq|\\geq|\\le|\\ge|<|>|=)\s*(\w*)`: `0 \leq a`
- `(\w*)\s*(?:\\leq|\\geq|\\le|\\ge|<|>|=)\s*([0-9-e,.^]+)`: `a < 10^9`
