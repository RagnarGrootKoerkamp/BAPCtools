# BAPCtools

BAPCtools is a tool for creating and developing problems following the
CLICS (DOMjudge/Kattis) problem format specified [here](https://icpc.io/problem-package-format/).

The aim of this tool is to run all necessary compilation, validation, and
testing commands while working on an ICPC-style problem.
Ideally one should never have to manually run any compilation or testing command themselves.

I'm interested to know who's using this, so feel free to inform me (e.g. via an issue) if so ;)
The current state is relatively stable, but things do change from time to
time since I'm not aware of usage outside of BAPC yet.

## Installation

> [!IMPORTANT]
> The latest version of BAPCtools is only compatible with problem format version
> [`2025-09`](https://icpc.io/problem-package-format/spec/2025-09.html).
> The [`bt upgrade` command](https://github.com/RagnarGrootKoerkamp/BAPCtools/blob/HEAD/doc/commands.md#upgrade)
> is a best-effort automated way to upgrade `legacy` problems to `2025-09`.
> To use BAPCtools with `legacy` problems,
> you can use the [`legacy` branch](https://github.com/RagnarGrootKoerkamp/BAPCtools/tree/legacy) of this repository,
> which is no longer maintained.

You can install the [bapctools-git AUR package](https://aur.archlinux.org/packages/bapctools-git/),
mirrored [here](https://github.com/RagnarGrootKoerkamp/bapctools-git).
You can also use the [Docker image](#Docker) or install [via Pip (experimental)](#Experimental-Pip-installation).
If you're interested in developing BAPCtools itself, see the installation instructions [at the end of this file](#Developing--Contributing-to-BAPCtools).

Otherwise, clone this repository and install the required dependencies manually.
(If you know how to make a Debian package, feel free to help out.)

- Python 3 (>= 3.10).
- The [ruamel.yaml library](https://pypi.org/project/ruamel.yaml/) via `pip install ruamel.yaml` or the `python-ruamel-yaml` Arch Linux package (`python3-ruamel.yaml` on Debian derivatives).
- The [colorama library](https://pypi.org/project/colorama/) via `pip install colorama` or the `python[3]-colorama` Arch Linux package.
- The `argcomplete` library for command line argument completion. Install via
  `python[3]-argcomplete`.

  - Note that actually using `argcomplete` is optional, but recommended.
    Detailed instructions are [here](https://argcomplete.readthedocs.io/en/latest/).

    TL;DR: Put `eval "$(register-python-argcomplete[3] bt)"` in your `.bashrc` or `.zshrc`.

Optional dependencies, required for some subcommands:

- The `latexmk` and `pdflatex` commands, provided by `texlive-bin` on Arch Linux and
  potentially some specific LaTeX packages (like tikz) provided by
  `texlive-extra`.
  These are only needed for building `pdf` files, not for `run` and `validate` and such.
- The [matplotlib library](https://pypi.org/project/matplotlib/) via `pip install matplotlib` or the `python[3]-matplotlib` Linux package.
  - This is optional and only used by the `solve_stats` command.
- The [requests library](https://pypi.org/project/requests/) via `pip install requests` or the `python[3]-requests` Linux package.
  - This is optional and only used by the commands that call the DOMjudge API (`export`, `solutions --order-from-css`, and `solve_stats`) or the Slack API (`create_slack_channels` command).
- The [questionary library](https://pypi.org/project/questionary/) via `pip install questionary`.
  - This is optional and only used by the `new_contest` and `new_problem` commands.

After cloning the repository, symlink [bin/tools.py](bin/tools.py) to somewhere in your `$PATH`. E.g., if `~/bin/` is in your `$PATH`, you can do:

```
$ ln -s ~/git/BAPCtools/bin/tools.py ~/bin/bt
```

### Windows
For Windows, the preferred way to use BAPCtools is inside the Windows Subsystem for Linux (WSL).

Note that BAPCtools makes use of symlinks for building programs.
By default, users are not allowed to create symlinks on Windows.
This can be fixed by enabling Developer Mode on Windows (only since Windows 10 version 1703, or newer).<br>
In case you're still having problems with symlinks in combination with Git after enabling this setting,
please try the suggestions at https://stackoverflow.com/a/59761201.
Specifically, `git config -g core.symlinks true` should do the trick,
after which you can restore broken symlinks using `git checkout -- path/to/symlink`.

### Native Windows
If you cannot or do not want to use WSL, you'll need the following in your `%PATH%`:

- `python` for Python 3
- `g++` to compile C++
- `javac` and `java` to compile and run Java.

Resource limits (memory limit/hard cpu time limit) are not supported.

### Docker

A docker image containing this git repo and dependencies, together with commonly
used languages, is provided at
[ragnargrootkoerkamp/bapctools](https://hub.docker.com/r/ragnargrootkoerkamp/bapctools).
This version may be somewhat outdated, but we intend to update it whenever dependencies change.
Ping me if you'd like it to be updated.
Alternatively, inside the Docker container, you can run `git -C /opt/BAPCtools pull` to update to the latest version of BAPCtools,
and use `pacman -Sy <package>` to install potential missing dependencies.

This image can be used for e.g.:

- running CI on your repo. Also see `bt gitlabci` which generates a
  `.gitlab-ci.yaml` file. Make sure to clear the entrypoint, e.g. `entrypoint: [""]`.
- running `bt` on your local problems. Use this command to mount your local
  directory into the docker image and run a command on it:
  ```
  docker run -v $PWD:/data --rm -it ragnargrootkoerkamp/bapctools <bt subcommands>
  ```

For maintainers, these are the steps to build and push an updated image:

```
$ sudo systemctl start docker
$ docker pull archlinux:latest
$ docker login
$ docker build . -t ragnargrootkoerkamp/bapctools
$ docker push ragnargrootkoerkamp/bapctools
$ ssh <server> sudo docker pull ragnargrootkoerkamp/bapctools
```

The last step is needed when your CI server is not automatically pulling the latest version.

### Experimental: Pip installation

We are transitioning towards adding BAPCtools to the Python Package Index (PyPI).
This is still experimental, but if you would like to try it out, you can install it using:
```shell
pip install 'git+https://github.com/RagnarGrootKoerkamp/BAPCtools.git'
```
This should be a complete installation (including optional dependencies and a `bt` executable) and should work on any Linux-ish system.
If you encounter any issues, please open an issue.

> [!IMPORTANT]
> Please do NOT `pip install bapctools` yet, as this will install a heavily outdated version of BAPCtools.

## Usage

BAPCtools can be run either from a problem directory or a contest directory. This
is automatically detected by searching for the `problem.yaml` file.

The most common commands and options to use on an existing repository are:

- [`bt run [-v] [submissions [submissions ...]] [testcases [testcases ...]]`](#run)
- [`bt test <submission> [--interactive | --samples | [testcases [testcases ...]]]`](#test)
- [`bt generate [-v] [--jobs JOBS]`](#generate)
- [`bt validate [-v] [--input | --answer] [--remove | --move-to DIR] [testcases [testcases ...]]`](#validate)
- [`bt pdf [-v]`](#pdf)

The list of all available commands and options is at [doc/commands.md#synopsis](doc/commands.md#synopsis),
and more information regarding the implementation is at [doc/implementation_notes.md](doc/implementation_notes.md).

### Run

- `bt run [-v] [submissions [submissions ...]] [testcases [testcases ...]]`

Without arguments, the `run` command runs all submissions against all testcases.
Specify one or more submissions and one or more testcases to only run the given submissions against the given testcases.

Before running the given submissions, this command first makes sure that all
generated testcases are up to date (in case `generators/generators.yaml` was
found). To disable automatically regenerating testcases, pass `-G`
(`--no-generate`), or add `no_generate: true` to a `.bapctools.yaml` file in the
problem or contest directory.

![run](doc/images/run.gif)

By default, `bt run` only prints one summary line per submission, and one additional line for each testcase with an unexpected result. Use `-v` to print one line per testcase instead.

![run -v](doc/images/run-v.gif)

### Test

- `bt test <submission> [--samples | [testcases [testcases ...]]]`

Use the `test` command to run a single submission on some testcases. The submission `stdout` and `stderr` are printed to the terminal instead of verified as an answer file.
Use `--samples` to run on the samples, or pass a list of testcases or directories containing testcases. Use `--interactive`/`-i` to run in interactive mode, where console input is forwarded to the submission.
This rebuilds and reruns the program until either `control-C` or `control-D` is pressed. It's also possible to supply the test case on the command line directly using e.g. `< /path/to/file.in` or `<<< "10 20"`.

![test](doc/images/test.png)

### Generate

- `bt generate [-v] [--jobs JOBS]`

Use the `generate` command to generate the testcases specified in `generators/generators.yaml`. See [doc/generators.md](doc/generators.md) for the specification of `generators.yaml` and see [doc/commands.md#generate](doc/commands.md#generate) for the full list of arguents.
Use `-j 0` to disable running multiple jobs in parallel (the default is `4`).

![generate](./doc/images/generate.gif)

### Validate

- `bt validate [-v] [--input | --answer] [--remove | --move-to DIR] [testcases [testcases ...]]`

Validate all the `.in` and `.ans` for all (given) testcases. It runs all validators from `input_validators`, `answer_validators`, and `output_validators`.

Validators can be one of

- a single-file program.
- a multi-file program with all files in a common directory.
- a .ctd CheckTestData file (this needs the `checktestdata` executable in your `$PATH`).
- a .viva file.

You can use `--remove` to delete all failing testcases or `--move <dir>` to move
them to a separate directory.

![validator](./doc/images/validate.png)

### Pdf

- `bt pdf [-v]`

Use this command to compile the `problem.en.pdf` from the `statement/problem.en.tex` LaTeX statement.
`problem.en.pdf` is written to the problem directory itself.

This can also be used to create the contest pdf by running it from the contest directory.

## Personal configuration file

For some command-line flags, it is convenient if they are always set to the same value, which differs per user
(e.g., `--username` or `--password` for commands that access a CCS like DOMjudge,
or `--jobs` to limit parallel execution) or per contest (e.g., which statement languages are used).
For this, you can create a configuration YAML file containing key-value pairs
in one of the following locations, from low to high priority:

- `$XDG_CONFIG_HOME/bapctools/config.yaml` (Unix-ish systems, where `$XDG_CONFIG_HOME` usually is `~/.config`)
- `%AppData%/bapctools/config.yaml` (Windows systems)
- `<contest directory>/.bapctools.yaml`

The keys in this config file can be any option that can be passed on the command-line.
Note that the keys should be written out in full (e.g., `username: jury` rather than `u: jury`)
and any hyphens should be replaced with an underscore (e.g., `no_bar: True` rather than `no-bar: True`).

These personal config files also allow to set the key `local_time_multiplier` to adjust hardcoded time limits intended for different hardware.
This might be useful for the CI or if your hadware is much faster or slower than the contest hardware.

## Developing / Contributing to BAPCtools

The recommended way to install all development dependencies is in a virtual environment,
created with `python3 -m venv venv` and activated with `. venv/bin/activate`.<br />
Install the development dependencies with `pip install --editable .[dev]`.

If you want to use your local development version of BAPCtools anywhere, you can create a symlink from any `bin` directory on your `$PATH` to the virtual environment, for example: `ln -s /path/to/BAPCtools/venv/bin/bt ~/bin/bt`

The Python code in the repository is formatted using [Ruff](https://github.com/astral-sh/ruff)
and type-checked using [mypy](https://mypy-lang.org/).
To enable the pre-commit hook,
run `pre-commit install` from the repository root.
All Python code will now automatically be formatted and type-checked on each commit.
If you want to run the hooks before creating a commit,
use `pre-commit run` (only staged files) or `pre-commit run -a` (all files).
