# LaTeX build system

This directory provides the class `bapc.cls` which is used as the base for compiling both single problems and
complete contests.

All temporary/build files go to `latex/build`.

## Manual compilation
If you want to compile a latex file by yourself, the easiest way to do that
is to copy over the `bapc.cls` file and to create a new latex file with documentclass `bapc`
which includes the latex file containing the problem statement.

## Compiling a single problem
- Create the directory `build/<problem>`.
- Link `build/problem` to `build/<problem>`.
- Symlink `build/problem/problem_statement` to `<problem dir>/problem_statement`.
- Create `build/problem/samples.tex` from the samples file.
    - This is hardcoded to:
```
\begin{Sample}
<content of input, with \newline after every line>
&
<content of output, with \newline after every line>
\end{Sample}
```
- Run `pdflatex` on `problem.tex` with the `-output-directory ./build/problem/` option.
- Link `<problemdir>/problem.pdf` to the output pdf.

The reason we use the `build/problem` symlink is twofold:
- By having data for each problem in a separate directory, latex can reuse build files.
- By making it a symlink, we don't have to fiddle with the latex code; just running `pdflatex` is enough.

## Compiling a contest
- Create `build/<contest>`.
- Link `build/contest` to `build/<contest>`.
- Link `build/contest/contest.tex` to `<contest dir>/contest.tex`.
- Link `build/contest/logo.png` to either the contest logo or placeholder logo.
- Create `build/contest/problems.tex`, containing includes for all problems and samples.
- Run `pdflatex` on `contest.tex`.

