# BAPCtools

BAPCtools is a tool for creating and developing problems following the
CLICS (DOMjudge/Kattis) problem format specified [here](https://clics.ecs.baylor.edu/index.php?title=Problem_format).

The aim of this tool is to run all necessary compilation, validation, and
testing commands while working on an ICPC-style problem.
Ideally one should never have to manually run any compilation or testing command themselves.

I'm interested to know who's using this, so feel free to inform me (e.g. via an issue) if so ;)
The current state is relatively stable, but things do change from time to
time since I'm not aware of usage outside of BAPC yet.

## Installation

For now the only way to use this is to clone the repository and install the
required dependencies manually.
(If you know how to make Debian and/or Arch packages, feel free to help out.)

-   Python 3 with the [yaml library](https://pyyaml.org/wiki/PyYAMLDocumentation) via `pip install
    pyyaml` or the `python[3]-yaml` Arch Linux package.
-   The `argcomplete` library for command line argument completion. Install via
    `python[3]-argcomplete`.
	- Note that actually using `argcomplete` is optional, but recommended.
	  Detailed instructions are [here](https://argcomplete.readthedocs.io/en/latest/).
	 
      TL;DR: Put `eval "$(register-python-argcomplete tools.py)"` in your `.bashrc` or `.zshrc`.
-   The `pdflatex` command, provided by `texlive-bin` on Arch Linux and
    potentially some specific LaTeX packages (like tikz) provided by
	`texlive-extra`.
	These are only needed for building `pdf` files, not for `run` and `validate` and such.

After cloning the repository, symlink [bin/tools.py](bin/tools.py) to somewhere in your `$PATH`. E.g., if `~/bin/` is in your `$PATH`, you can do:

```
% ln -s ~/git/BAPCtools/bin/tools.py ~/bin/bt
```

### Windows

For Windows, you'll need the following in your
`path`:
- `Python` for Python 3
- `g++` to compile C++
- `javac` and `java` to compile and run `java`.

Note that colorized output does not work.
Resource limits (memory limit/hard cpu time limit) are also not supported.

## Usage

BAPCtools can be run either from a problem directory or a contest directory. This
is automatically detected by searching for the `problem.yaml` file.

The most common commands and options to use on an existing repository are:

- [`bt run [-v] [submissions [submissions ...]] [testcases [testcases ...]]`](#run)
- [`bt test [-v] submission [--samples | [testcases [testcases ...]]]`](#test)
- [`bt generate [-v] [--jobs JOBS]`](#generate)
- [`bt validate [-v] [testcases [testcases ...]]`](#validate)
- [`bt pdf [-v]`](#pdf)

The list of all available commands and options is at [doc/commands.md#synopsis](doc/commands.md#synopsis),
and more information regarding the implementation is at [doc/implementation_notes.md](doc/implementation_notes.md).

### Run
### Test
### Generate
### Validate
### Pdf

### Run submissions

From inside either a problem or contest directory: `tools.py run [-v] [-v]
[submissions] [testcases]`

This runs all submissions in the problem/contest on all testdata for the
problem. Use `-v` to make it print testcases where submissions fail.

![run](./doc/images/02_run.gif)

You can also run one (or multiple) given submissions and see the status with
`-v`. Note that the wrong answer verdict is green here because the submission is
expected to get wrong answer. Unexpected outcomes are always printed, even
without `-v`. If the given and expected answer are a single line only, the diff
is given inline. Otherwise a small snippet is printed on the lines below.

![run single submission](./doc/images/03_run_submission.gif)

### Generating output files

`tools.py generate [-f] [submission]` chooses a submission or uses the given
submission to generate a `.ans` file for every `.in` file. Supply `-f` to
overwrite changed answer files.

![generate ans files](./doc/images/04_generate.gif)

### Validating input/answer/output files

`tools.py validate` runs all validator files in the `input_validator` and
`output_validator` directories against all testcases.

Validators can be one of
 - an executable,
 - a c++ program,
 - a .ctd CheckTestData file (this needs the `checktestdata` executable in the
   PATH).
- a .viva file.

See the Notes on Validation section further down for more info.

You can use `--remove` to delete all failing testdata or `--move <dir>` to move
them to a separate directory.

![validator](./doc/images/05_validate.png)

### Building problem PDF

`tools.py pdf [--web]` creates a PDF of the problem statement or entire contest,
depending on where you run it. The `--web` flag removes empty pages and makes it
single sided. The output file is a `example_problem/problem.pdf` like
[this](./doc/images/problem.pdf) symlink to a build directory. (See the Notes on LaTeX
further down.)

Running it from a contest directory creates a `contest.pdf` like
[this](./doc/images/contest.pdf) file in the contest directory.

*   The problem letter and time limit are extracted from `domjudge-problem.ini`.
*   Samples are automatically included from the `data/sample` directory.
*   The `problem_statement/problem.en.tex`
    [file](skel/problem/problem_statement/problem.en.tex) consists of:
    -   `\problemname{<name>}`
    -   (optionally) a figure
    -   the problem statement
    -   an `Input` section or environment
    -   an `Output` section or environment
