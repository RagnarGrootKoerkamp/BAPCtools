# Documentation for subcommands

This document explains all subcommands and their flags, sorted per category.

Unless otherwise specified, command work both on the problem and contest level.

## Global flags

The flags below work for any subcommand:

* `--verbose`/`-v`: Without this, only failing steps are printed to the terminal. With `-v`, progress bars print one line for each processed item. Pass `-v` twice to see all commands that are executed.
* `--contest <directory>`: The directory of the contest to use, if not the current directory. At most one of `--contest` and `--problem` may be used. Useful in CI jobs.
* `--problem <directory>`: The directory of the problem to use, if not the current directory. At most one of `--contest` and `--problem` may be used. Useful in CI jobs.
* `--no-bar`: Disable showing progress bars. This is useful when running in non-interactive contexts (such as CI jobs) or on platforms/terminals that don't handle the progress bars well.
* `--error`/`-e`: show full output of failing commands using `--error`. The default is to show a short snippet only.
* `--cpp_flags`: Additional flags to pass to any C++ compilation rule. Useful for e.g. `--cpp_flags=-fsanitize=undefined`.
* `--force_build`: Force rebuilding binaries instead of reusing cached version.

## Problem development

### `run`



### `test`

`bt test` only works for a single problem, and must be called as
```
bt test <submission> [<testcases>].
```

It runs the given submission against the specified testcases (or all testcases if not set) and prints the submission `stdout` and `stderr` to the terminal. The submission output is not validated or checked for correctness. However, time limits and timeouts will be reported. For interactive problems, the interaction is shown.

This is useful for running submissions without having to compile them manually. Also, it doesn't give away whether the submission is ACCEPTED or WRONG_ANSWER, which may be useful when trying to solve a problem before looking at the solutions.

**Flags**

- `<submission>`: The path to the submission to run.
- `[<testcases>]`: Paths to the testcases (`.in`, `.ans`, basename, or directory) to run the submission on. Can not be used together with `--samples`.
- `--samples`: Run the submission on the samples only. Can not be used together with explicitly listed testcases.
- `--timeout <second>`/`-t <second>`: The timeout to use for the submission.
- `--memory <bytes>`/`-m <bytes>`: The maximum amount of memory in bytes the any submission may use.


### `generate`

Use the `generate` command to generate the testcases specified in `generators/generators.yaml`. The syntax of this file is described [here](https://github.com/RagnarGrootKoerkamp/BAPCtools/blob/generated_testcases/doc/generated_testcases_v2.yaml). This should become part of the problem archive spec as well.

This command tries to be smart about not regenerating testcases that are up to date. When the generator and its invocation haven't changed, nothing will be done.

Any files in `data/` that are not tracked in `generators.yaml` will raise a warning.

**Flags**

- `--force`/`-f`: By default, `generate` will not overwrite any files, but instead warn that they will change. Pass `--force` to overwrite existing files.
- `--samples`: Even with `--force`, samples won't be overwritten by default. `--force --samples` also overwrites samples. (Samples usually have a manually curated input and output that should not be overwritten easily.)
- `--clean`/`-c`: Clean untracked files instead of warning about them. WARNING: This may delete manually created testcases that are not (yet) mentioned in `generators.yaml`.
  One time where this is useful, is when automatically numbered testcases get renumbered. In this case, the `generate` command will complain about the old numbered testcases, and `clean` can be used to remove those.
- `--jobs <number>`/`-j <number>`: The number of parallel jobs to use when generating testcases. Defaults to `4`. Set to `0` or `1` to disable parallelization.
- `--timeout <seconds>`/`-t <seconds>`: Override the default timeout for generators and visualizers (`30s`) and submissions (`1.5*timelimit+1`).


### `clean`

The `clean` command deletes all generated testdata from the `data/` directory. It only removes files that satisfy both these conditions:
- The `.in` corresponding to the current file was generated.
- The extension of the current file is handled by the problem archive format: `.in`, `.ans`, `.interaction`, `.hint`, `.desc`, `.png`, `.jpg`, `.jpeg`, `.svg`.

Furthermore, it removes generated `testdata.yaml`.

**Flags**

- `--force`/`-f`: When this is passed, all untracked files (i.e. files not matching any rule in `generators/generators.yaml`) are deleted. Without `--force`, such files raise a warning.


### `pdf`

Renders a pdf for the current problem or contest. The pdf is written to `problem.pdf` or `contest.pdf` respectively, and is a symlink to the generated pdf which is in a temporary directory.

**Flags**

- `--no-timelimit`: When passed, time limits will not be shown in the problem/contest pdfs.
- `--all`/`-a`: When run from the contest level, this enables building pdfs for all problems in the contest as well.
- `--cp`: Instead of symlinking the final pdf, copy it into the problem/contest directory.
- `--web`: Build a web version of the pdf. This uses [contest-web.tex](../latex/contest-web.tex) instead of [contest.tex](../latex/contest.text) and [solutions-web.tex](../latex/solutions-web.tex) instead of [solutions.tex](../latex/solutions.tex). In practice, the only thing this does is to remove empty _this is not a blank page_ pages.

**LaTeX setup**

The per-problem pdfs are created inside `<tmpdir>/<problemname>`:
- Copy [problem.tex](../latex/problem.tex) and substitute the values (label, name, timelimit, author, ...) for the current problem.
- Symlink the `problem_statement/` directory.
- Build the `samples.tex` file from the files in `data/samples/`.
- Symlink [bapc.cls](../latex/bapc.cls).
- Compile `problem.tex` using `pdflatex -interaction=nonstopmode -halt-on-error -output-directory <tmpdir>/<problemname>`.

The contest pdf is created in `<tmpdir>/<contestname>` like this:
- Symlink `<problem>/problem_statement/` for each problem.
- Create the `<problem>/samples.tex` for each problem.
- Symlink [contest.tex](../latex/contest.tex) (or [contest-web.tex](../latex/contest-web.tex)), [bapc.cls](../latex/bapc.cls), and [images/](../latex/images).
- Look for a `logo.{pdf,png,jpg}` in the contest directory or the directory above it, and symlink it. Fall back to a default `logo.pdf`.
- Create a simple [contest_data.tex](../latex/contest-data.tex) containing variables with the name, subtitle, year, and authors of the contest. This is included by `contest.tex`.
- Create `contest-problems.tex`, containing the per-problem information and includes. It contains one filled in copy of [contest-problem.tex](../latex/contest-problem.tex) for each problem.
- Compile `contest.tex` using `pdflatex -interaction=nonstopmode -halt-on-error -output-directory <tmpdir>/<contestname>`.


### `solutions`

Renders a pdf for the current problem or contest. The pdf is written to `problem.pdf` or `contest.pdf` respectively, and is a symlink to the generated pdf which is in a temporary directory.

**Flags**

- `--order`: The order of the problems, e.g. `BDCA`. Can be used to order problems from easy to difficult. When labels have multiple letters, `B1,A1,A2,B2` is also allowed.
- `--cp`: Instead of symlinking the final pdf, copy it into the contest directory.
- `--web`: Build a web version of the pdf. This uses [contest-web.tex](../latex/contest-web.tex) instead of [contest.tex](../latex/contest.text) and [solutions-web.tex](../latex/solutions-web.tex) instead of [solutions.tex](../latex/solutions.tex). In practice, the only thing this does is to remove empty _this is not a blank page_ pages.


**LaTeX setup**

Solutions are rendered in a similar way to the contest pdf. It uses all `problem_statement/solution.tex` files as input. The main difference is the inclusion of
- `solutions_header.tex`
- `solutions_footer.tex`

**Solve stats**

Apart from this, there is some special support for handling _solve stats_. To use this, create the following directory layout:
- `<contest>/solve_stats/problem_stats.tex`: Contains one line for each problem label:
  ```
  \newcommand{\solvestatsA}{\printsolvestats{<number submissions>}{<number accepted>}{<number unknown>}}
  ```
  When this file is present, each `solution.tex` may use `\solvestats` to print a line like:
  ```
  Statistics: 15 submissions, 3 accepted, 8 unknown
  ```
- `<contest>/solve_stats/languages.tex`: a (standalone) plot of the language distribution of all submission. This may be included by the `solution_header.tex` or `solution_footer.tex`.

- `<contest>/solve_stats/activity/<label>.tex`: One file per problem, containing a (standalone) plot of the submissions over time. These will automatically be included on the solution slides for each problem when available.

All the files in the `solve_stats` directory can be generated using https://github.com/hex539/scoreboard and also [this issue](https://github.com/hex539/scoreboard/issues/7).

### `stats`

`bt stats` prints a table of statistics for the current problem or the problems in the current contest.
This table contains:
- The problem label and shortname.
- Whether `problem.yaml` and `domjudge.ini` are found.
- Whether `problem_statement/problem.en.tex` and `problem_statement/solution.tex` are found.
- Whether the problem has any `input_validators` and `output_validators`.
- The number of `sample` and `secret` testcases.
- The number of `accepted`, `wrong_answer`, and `time_limit_exceeded` solutions.
- The number of `c++`, `java`, `python2`, and `python3` solutions.
- An optional comment, as specified by the `comment:` field in `problem.yaml`.
- When `verified:` is set to `true` in `problem.yaml`, the comment will be shown in green.

## Problem validation

### `input`

Use `bt input [<testcases>]` to validate the `.in` files for the given testcases, or all testcases when not specified. When running for a single problem, testcases can be given as one of:
- A `.in` file: `data/sample/1.in`
- A `.ans` file: `data/sample/1.ans`
- A testcase name: `data/sample/1`
- A directory: `data/sample`. All `.in` files under the given directory will be validated.

### `output`

`bt output <testcases>` is similar to `bt input` but validates `.ans` files instead of `.in` files.

### `validate`

`bt validate` is a convenience command that validates both input and output files.

**Flags**

It supports the following flags when run for a single problem:
- `[testcases]`: a list of testcases and/or directories to validate. See `input` above for allowed formats. When not set, all testcases are validated.
- `--remove`: when passed, all invalid testcases are deleted.
- `--move_to <directory>`: when passed, all invalid testcases are moved to the given directory.

### `constraints`

Validators based on [headers/validation.h](../headers/validation.h) can take a `--constraints_file <file_path>` flag.
After validation is done, the validator will write a file to the given path containing the minimum and maximum values seen for all numbers read in the input or output. Each line in the output file should look like:
```
<source_location> <bool reached minimum> <bool reached maximum> <minimum allowed> <maximum allowed> <minimum seen> <maximum seen>
```

For example, the code `v.read_integer("a", 1, 1000)` could generate the line:
```
/tmp/bapctools_abcdef/findmyfamily/input_validators/input_validator/input_validator.cpp:7 0 0 999 999 1 1000
```

Note that everything up to and including `:7` is the file and line of the `read_integer` statement. The two zeros indicate that the minimum and maximum value were not reached. The `999 999` indicate that we read `a` only once, and it was equal to `999`. The final `1 1000` indicate the valid range of `a`.

BAPCtools will accumulate these values over all testcases, and print a warning when the minimum or maximum value of a `read` statement was never reached, like so:

```
WARNING: BOUND NOT REACHED: The value at input_validator.cpp:7 was never equal to the upper bound of 1000. Max value found: 999
```

This system works for any validator that accepts the `--constraints_file` flag. This is determined by searching all sources for `constraints_file`.

Note: `validation.h` requires `std::source_location`, which is available since C++20. BAPCtools will automatically add this as an additional C++ flag when needed. This may not work on systems not supported C++20.

**Parsing the LaTeX statement**

Besides checking the testdata for the allowed minimum and maximum values, `bt constraints` also runs some regexes over the input validator, output validator, and LaTeX sources to look for numeric bounds. These are then displayed next to each other to make it easy to manually check that the bounds used in the statement match the bounds used in the validators.

This output may look like:
```
~bapc/findmyfamily % bt constraints
PROBLEM findmyfamily
findmyfamily/input_validators/input_validator/input_validator.cpp
findmyfamily/output_validators/output_validator/output_validator.cpp
           VALIDATORS         |         PROBLEM STATEMENT
              t  1            |           maxn  3\cdot10^5
              t  1000         |              k  1
              n  3            |              k  1000
              a  1            |              n  3
              a  1'000'000'000|              n  3
                              |            h_1  1
                              |            h_n  10^9
                              |            a_i  1
```

## Creating a new contest/problem

### `new_contest`

This command creates a new contest. Can be called as `bt new_contest` or `bt new_contest <contest name>`.
Settings for this contest will be asked for interactively. The following files are copied from [skel/contest](../skel/contest):

- `contest.yaml` containing data for rendering the contest pdf.
- `problems.yaml` containing the list of problems and their labels.
- `languages.yaml` containing the list of languages to use. This may be deleted to use the default instead, or changed to e.g. only allow a subset of languages.
- `logo.pdf` for the contest pdf.
- `solution_{header,footer}.tex` contains extra slides for the solutions presentation.

```
/tmp/tmp % bt new_contest
name: NWERC 2020
subtitle []: The Northwestern European Programming Contest 2020
dirname [nwerc2020]:
author [The NWERC 2020 jury]:
testsession? [n (y/n)]: n
year [2020]:
source [NWERC 2020]:
source url []: 2020.nwerc.eu
license [cc by-sa]:
rights owner [author]:
```

### `new_problem`

Create a new problem directory and fill it with skel files. If `problems.yaml` is present, also add the problem to it. Information can be passed in either interactively or via command line arguments:
```
~nwerc2020 % bt new_problem
problem name: Test Problem
dirname [testproblem]:
author: Ragnar Groot Koerkamp
validation (default/custom/custom interactive) [default]:
LOG: Copying /home/philae/git/bapc/BAPCtools/skel/problem to testproblem.
```

```
~nwerc2020 % bt new_problem 'Test Problem 2' --author 'Ragnar Groot Koerkamp' --validation interactive
LOG: Copying /home/philae/git/bapc/BAPCtools/skel/problem to testproblem2.
```

Files are usually copied from [skel/problem](../skel/problem), but this can be overridden as follows:

- If the `--skel <directory>` flag is specified, that directory is used instead.
- If either the current (contest) directory or the parent directory contains a `skel/problem` directory, that is used instead. This can be used to override the default problem template on a per-contest basis.

**Flags**

- `[<problem name>]`: The name of the problem. Will be asked interactively if not specified.
- `--author`: The author of the problem. Will be asked interactively if not specified.
- `--validation`: The validation mode to use. Must be one of `default`, `custom`, `custom interactive`.

### `gitlabci`

`bt gitlabici` prints configuration for Gitlab Continuous Integration to the terminal. This can be piped into the `.gitlab-ci.yml` file in the root of the repository. When there are multiple contests, just append the `bt gitlabci` of each of them, but deduplicate the top level `image:` and `default:` keys.

Example output:
```
~nwerc2020 % bt gitlabci
image: bapctools

default:
  before_script:
    - git -C /cache/BAPCtools pull || git clone https://github.com/RagnarGrootKoerkamp/BAPCtools.git /cache/BAPCtools
    - ln -s /cache/BAPCtools/bin/tools.py bt

contest_pdf_nwerc2020:
  script:
      - ./bt pdf --cp --no-bar --contest nwerc2020
      - ./bt solutions --cp --no-bar --contest nwerc2020
  only:
    changes:
      - nwerc2020/testproblem/problem_statement/**/*

  artifacts:
    expire_in: 1 week
    paths:
      - nwerc2020/contest.pdf
      - nwerc2020/solutions.pdf



verify_testproblem:
  script:
      - ./bt all --cp --no-bar --problem nwerc2020/testproblem
  only:
    changes:
      - nwerc2020/testproblem/**/*
  artifacts:
    expire_in: 1 week
    paths:
      - nwerc2020/testproblem/problem.pdf
```

The default behaviour is:
- Use the `bapctools` Docker image. This has to be installed manually from the [Dockerfile](../Dockerfile) found in the root of the repository.
- Before each stage, pull `BAPCtools` to the `/cache` partition. This makes sure to always use the latest version of BAPCtools.
- For contests: build the problem and solutions pdf and cache these artefacts 1 week.
- For problems: run `bt all` on the problem and keep the problem pdf for 1 week.

We use the following configuration for the gitlab runners:
```
[[runners]]
  name = "BAPC group runner"
  url = "<redacted>"
  token = "<redacted>"
  executor = "docker"
  [runners.custom_build_dir]
  [runners.docker]
    tls_verify = false
    image = "bapctools"
    privileged = false
    disable_entrypoint_overwrite = false
    oom_kill_disable = false
    disable_cache = false
    volumes = ["/cache"]
    shm_size = 0
    pull_policy = "never"
    memory = "2g"
    memory_swap = "2g"
  [runners.cache]
    [runners.cache.s3]
    [runners.cache.gcs]
  [runners.docker.tmpfs]
    "/tmp" = "rw,exec"
```

## Exporting

### `samplezip`

Create `contest/samples.zip` containing the sample `.in` and `.ans` files for all samples in the current problem or contest. Samples are always numbered starting at `1`:

```
~bapc % bt samplezip
Wrote zip to samples.zip
~bapc % unzip -l samples.zip
Archive:  samples.zip
  Length      Date    Time    Name
---------  ---------- -----   ----
       18  2020-05-06 20:36   A/1.in
        3  2020-05-06 20:36   A/1.ans
       44  2020-05-06 20:36   A/2.in
        4  2020-05-06 20:36   A/2.ans
        2  2020-05-06 20:36   B/1.in
        8  2020-05-06 20:36   B/1.ans
        2  2020-05-06 20:36   B/2.in
        4  2020-05-06 20:36   B/2.ans
        8  2020-05-06 20:36   C/1.in
        8  2020-05-06 20:36   C/1.ans
...
```


### `zip`

This creates a problem or contest zip that can be directly imported into DOMjudge.
Specify the `--kattis` flag for a zip compatible with `problemtools`. Differences are explained below.

When run for a problem:
- Build the problem pdf.
- Verify problem input and output, with constraint checking.
- Write a zip containing all problem data to `contest/<problemlabel>.zip`, e.g. `contest/A.zip`.

When run for a contest:
- First build a zip for each problem, as above.
- Build the contest pdf.
- Build the contest solution slides.
- Write the contest pdf and all problem zips to a single zip: `contest/<contest>.zip`.

**Flags**

- `--skip`: Do not rebuild problem zips when building a contest zip.
- `--force`/`-f`: Skip validating input and output. This is useful to speed up regenerating the zip with only minimal changes.
- `--no-solutions`: Do not build solution slides for the contest zip.
- `--kattis`: Differences for Kattis export are:
  - Problems zips are written to `<shortname>.zip` instead of `<problemlabel>.zip`.
  - Kattis doesn't use a contest pdf, solution slides, and `contest/samples.zip`.
  - The contest level zip is written to `contest/<contest>-kattis.zip`
  - Kattis needs the `input_validators` directory, while DOMjudge doesn't use this.
  - Kattis problem zips get an additional top level directory named after the problem shortname.


## Misc

### `all`

This is a convenience command (mostly for use in CI) that runs the following subcommands in sequence for the current problem or each problem in the current contest:
- Build the problem pdf
- Generate testcases
- Validate input
- Validate output
- Run all submissions

This supports the `--cp` and `--no-timelimit` flags which are described under the `pdf` subcommand.


### `sort`

Prints a list of all problems in the current contest (or single problem), together with their letter/ID:

```
~bapc % bt sort
A : appealtotheaudience
B : breakingbranches
C : conveyorbelts
D : deckrandomisation
E : efficientexchange
F : findmyfamily
G : gluttonousgoop
H : historicexhibition
I : inquiryii
J : jazzitup
K : keephiminside
L : luckydraw
```

### `tmp`

`bt tmp` prints the temporary directory that's used for all compilation output, run results, etc for the current problem or contest:

```
~bapc/findmyfamily % bt tmp
/tmp/bapctools_ef27b4/findmyfamily
```

This is useful for development/debugging in combination with `cd`:
```
cd `bt tmp`
```
