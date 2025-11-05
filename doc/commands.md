# Documentation for subcommands

This document explains all subcommands and their flags, sorted per category.
The [implementation notes](implementation_notes.md) contain more information about various topic not covered here.

Unless otherwise specified, commands work both on the problem and contest level.

**Allowed subcommands and options are also available with `bt --help` and `bt <command> --help`.**

# Synopsis

This lists all subcommands and their most important options.

- Problem development:
  - [`bt run [-v] [-t TIME_LIMIT] [submissions [submissions ...]] [testcases [testcases ...]]`](#run)
  - [`bt test [-v] [-t TIMEOUT] submission [--interactive | --samples | [testcases [testcases ...]]]`](#test)
  - [`bt time_limit [-a] [-w] [submissions [submissions ...]] [testcases [testcases ...]]`](#time_limit)
  - [`bt generate [-v] [-t TIMEOUT] [--add] [--clean] [--check-deterministic] [--jobs JOBS] [--no-validators] [--no-visualizer] [--reorder] [testcases [testcases ...]]`](#generate)
  - [`bt pdf [-v] [--all] [--web] [--cp] [-w] [-o PROGRAM] [--no-time-limit]`](#pdf)
  - [`bt solutions [-v] [--web] [--cp] [-w] [-o PROGRAM] [--order ORDER]`](#solutions)
  - [`bt problem_slides [-v] [--cp] [-w] [-o PROGRAM]`](#problem_slides)
  - [`bt stats`](#stats)
  - [`bt fuzz [-v] [-t TIME] [--timeout TIMEOUT] [testcases [testcases ...]]`](#fuzz)
- Problem validation
  - [`bt input [-v] [testcases [testcases ...]]`](#input)
  - [`bt output [-v] [testcases [testcases ...]]`](#output)
  - [`bt validate [-v] [--input | --answer | --invalid | --valid-output | --generic [TYPE]] [--remove | --move-to DIR] [testcases [testcases ...]]`](#validate)
  - [`bt constraints [-v]`](#constraints)
  - [`bt check_testing_tool [submissions [submissions ...]] [testcases [testcases ...]`](#check_testing_tool)
- Creating new contest/problems
  - [`bt new_contest [contestname]`](#new_contest)
  - [`bt new_problem [problemname] [--author AUTHOR] [--type {pass-fail,float,custom,interactive,...}] [--defaults] [--skel SKEL]`](#new_problem)
  - [`bt skel [--skel SKEL] directory [directory ...]`](#skel)
  - [`bt rename_problem [problemname]`](#rename_problem)
  - [`bt gitlabci [--latest-bt]`](#gitlabci)
  - [`bt forgejo_actions [--latest-bt]`](#forgejo_actions)
  - [`bt github_actions`](#github_actions)
- Exporting
  - [`bt samplezip`](#samplezip)
  - [`bt zip [--skip] [--force] [--no-generate] [--kattis] [--no-solutions]`](#zip)
  - [`bt export`](#export)
- Misc
  - [`bt all [-v] [--cp] [--no-time-limit] [--check-deterministic]`](#all)
  - [`bt solve_stats [--contest-id CONTESTID] [--post-freeze]`](#solve_stats)
  - [`bt sort`](#sort)
  - [`bt update_problems_yaml [--colors COLORS] [--sort]`](#update_problems_yaml)
  - [`bt upgrade`](#upgrade)
  - [`bt tmp [--clean]`](#tmp)
  - `bt create_slack_channels --token xoxb-...`

# Global flags

The flags below work for any subcommand:

- `--verbose`/`-v`: Without this, only failing steps are printed to the terminal. With `-v`, progress bars print one line for each processed item. Pass `-v` twice to see all commands that are executed.
- `--contest <directory>`: The directory of the contest to use, if not the current directory. At most one of `--contest` and `--problem` may be used. Useful in CI jobs.
- `--problem <directory>`: The directory of the problem to use, if not the current directory. At most one of `--contest` and `--problem` may be used. Useful in CI jobs.
- `--memory <MB>`/`-m <MB>`: Override the maximum amount of memory in MB a program (submission/generator/etc.) may use.
- `--no-bar`: Disable showing progress bars. This is useful when running in non-interactive contexts (such as CI jobs) or on platforms/terminals that don't handle the progress bars well.
- `--error`/`-e`: show full output of failing commands using `--error`. The default is to show a short snippet only.
- `--force-build`: Force rebuilding binaries instead of reusing cached version.
- `--lang`: select languages to use for LaTeX commands. The languages should be specified by language codes like `en` or `nl`.

# Problem development

## `run`

The `run` command is used to run some or all submissions against some or all testcases.
The syntax is:

```
bt run [<submissions and/or testcases>]
```

This first makes sure all generated testcases are up to date and then runs the given submissions (or all submissions by default) against the given testcases (or all testcases by default).

By default, this prints one summary line per submission containing the slowest testcase.
If the submission failed, it also prints the testcases for which it failed.
Use `bt run -v` to show results for all testcases.

**Flags**

- `[<submissions and/or testcases>]`: Submissions and testcases may be freely mixed. The arguments containing `data/` or having `.in` or `.ans` as extension will be treated as testcases. All other arguments are interpreted as submissions. This argument is only allowed when running directly from a problem directory, and does not work with `--problem` and `--contest`.

  Testcases and submissions should be passed as a relative or absolute path to the testcase/submission.

  When submissions or testcases is not specified, they default to all submissions in `submissions/` and all testcases under `data/{sample,secret}` respectively.

  **Submission** paths can take a few forms:

  - The path of the single file: `submissions/accepted/submission.py`
  - The path of the submission directory (when it contains multiple files): `submissions/accepted/directory_submission/`
  - One of the directories inside `submissions/`: `submissions/time_limit_exceeded`. This will add all submissions in the given directory.
  - Any file/directory outside `submission` is also allowed. Directories will be interpreted as a single multi-file submission.

  Duplicate submissions will deduplicated.

  **Testcases** may be referred to in a few ways:

  - The path of the `.in` file: `data/secret/1.in`
  - The path of the `.ans` file: `data/secret/1.ans` (any other extension also works, even if the file doesn't exist)
  - The base name of the testcase: `data/secret/1`
  - A directory: `data/secret`. In this case, all `.in` files that are (nested) in this directory will be used.

  Testcases must always be inside the `data` directory. Anything outside `data/` will raise an error.

  Duplicate testcases will deduplicated. Hence, you may pass `data/secret/*` and `1.in` and `1.ans` will not trigger the testcase twice.

- `--samples`: Run the given submissions against the sample data only. Not allowed in combination with passing in testcases directly.
- `--no-generate`/`-G`: Do not generate testcases before running the submissions. This usually won't be needed since checking that generated testcases are up to date is fast.
- `--time-limit <second>`/`-t <second>`: The time limit to use for the submission.
- `--timeout <second>`: The timeout to use for the submission.
- `--table`: Print a table of which testcases were solved by which submissions. May be used to deduplicate testcases that fail the same submissions.
- `--overview`/`-o`: Print a live overview of the received verdicts for all submissions and testcases. If combined with `--no-bar` only the final table is printed.
- `--no-testcase-sanity-checks`: when passed, all sanity checks on the testcases are skipped. You might want to set this in `.bapctools.yaml`.
- `--sanitizer`: when passed, run submissions with additional sanitizer flags (currently only C++). Note that this removes all memory limits for submissions.
- `--visualizer`: when passed, run the output visualizer.

## `test`

`bt test` only works for a single problem, and must be called as

```
bt test <submission> [<testcases>].
```

It runs the given submission against the specified testcases (or all testcases if not set) and prints the submission `stdout` and `stderr` to the terminal. The submission output is not validated or checked for correctness. However, time limits and timeouts will be reported. For interactive problems, the interaction is shown.

This is useful for running submissions without having to compile them manually. Also, it doesn't give away whether the submission is ACCEPTED or WRONG_ANSWER, which may be useful when trying to solve a problem before looking at the solutions.

**Flags**

- `<submission>`: The path to the submission to run. See `run <submissions>` for more.
- `--interactive`/`-i`: Use terminal input as test data. `stdin` is forwarded directly to the submission. This rebuilds and reruns the submission until either the end of the input (`control-D`) or till BAPCtools is terminated (`control-C`).

  It is also possible to pipe in testcases using e.g.

  ```
  bt test submissions/accepted/author.py --interactive < data/samples/1.in
  ```

  or

  ```
  bt test submissions/accepted/author.py -i <<< "10 20"
  ```

  in this case, the submission is only run once instead of repeatedly.

- `[<testcases>]`: The testcases to run the submission on. See `run <testcases>` for more. Can not be used together with `--samples`.
- `--samples`: Run the submission on the samples only. Can not be used together with explicitly listed testcases.
- `--timeout <second>`/`-t <second>`: The timeout to use for the submission.

## `time_limit`

The `time_limit` command is used determine a time limit based on the `time_multipliers`: `ac_to_time_limit` and `time_limit_to_tle`.
The syntax is:

```
bt time_limit [<submissions and/or testcases>]
```

**Flags**
- `--write`/`-w`: write the determined time limit to `problem.yaml`
- `--all`/`-a`: run all submissions not only AC and TLE submissions.
- `<submissions>`: The path to the submission to use to determine the time limit. See `run <submissions>` for more.
- `<testcases>`: The path to the testcases to use determine the time limit. See `run <testcases>` for more.

## `generate`

Use the `generate` command to generate the testcases specified in `generators/generators.yaml`. The syntax of this file is described in [generators.md](generators.md) and [generators.yaml](generators.yaml) is an example.

This command tries to be smart about not regenerating testcases that are up to date. When the generator and its invocation haven't changed, nothing will be done.

Any files in `data/` that are not tracked in `generators.yaml` will be removed.

Pass a list of testcases or directories to only generate a subset of data. See [run](#run) for possible ways to pass in testcases.

**Flags**

- `--check-deterministic`: Check that the .in files are generated deterministically for all test cases, skipping the up-to-date check.
- `--add [<testcases>, <directories>]`: Add the testcases (inside the directories) as `copy` entries in the `generator.yaml`
- `--clean`: Delete all cached files.
- `--reorder`: Runs all submissions that should fail and reorders the testcases in the given directories by difficulty.
- `--jobs <number>`/`-j <number>`: The number of parallel jobs to use when generating testcases. Defaults to half the number of cores. Set to `0` to disable parallelization.
- `--timeout <seconds>`/`-t <seconds>`: Override the default timeout for generators and visualizers (`30s`) and submissions (`1.5*time_limit+1`).
- `--no-validators`: Ignore the results of input and output validators.
  (They are still run.)
- `--no-solution`: Skip generating .ans or .interaction files with the solution.
- `--no-visualizer`: Skip generating graphics with the visualiser.
- `--no-testcase-sanity-checks`: when passed, all sanity checks on the testcases are skipped. You might want to set this in `.bapctools.yaml`.

## `pdf`

Renders a pdf for the current problem or contest. The pdf is written to `problem.en.pdf` or `contest.en.pdf` respectively.
If there are problem statements (and problem names in `problem.yaml`) present for other languages, creates those PDFs as well.

**Note:** All LaTeX compilation is done in tmpfs (`/tmp/` on linux). The resulting pdfs will be symlinks into the temporary directory. See the [Implementation notes](implementation_notes.md#building-latex-files) for more.

**Flags**

- `--all`/`-a`: When run from the contest level, this enables building pdfs for all problems in the contest as well.
- `--cp`: Instead of symlinking the final pdf, copy it into the problem/contest directory.
- `--no-time-limit`: When passed, time limits will not be shown in the problem/contest pdfs.
- `--watch`/`-w`: Continuously compile the pdf whenever a `problem.en.tex` changes. Note that this does not pick up changes to `*.yaml` configuration files. Note that this implies `--cp`.
- `--open <program>`/`-o <program>`: Open the continuously compiled pdf (with a specified program).
- `--web`: Build a web version of the pdf. This uses [contest-web.tex](../latex/contest-web.tex) instead of [contest.tex](../latex/contest.tex) and [problem-web.tex](../latex/problem-web.tex) instead of [problem.tex](../latex/problem.tex). In practice, the only thing this does is to remove empty _this is not a blank page_ pages and make the pdf single sides.
- `-1`: Run the LaTeX compiler only once.

## `solutions`

Renders a pdf with solutions for the current problem or contest. The pdf is written to `solution.en.pdf` or `solutions.en.pdf` respectively, and is a symlink to the generated pdf which is in a temporary directory.
See the [Implementation notes](implementation_notes.md#building-latex-files) for more.

**Flags**

- `--cp`: Instead of symlinking the final pdf, copy it into the contest directory.
- `--order`: The order of the problems, e.g. `BDCA`. Can be used to order problems from easy to difficult. When labels have multiple letters, `B1,A1,A2,B2` is also allowed.
- `--order-from-ccs`: Order the problems by increasing difficulty, extracted from the api, e.g.: https://www.domjudge.org/demoweb. Defaults to value of `api` in contest.yaml.
- `--contest-id`: Contest ID to use when reading from the API. Only useful with `--order-from-ccs`. Defaults to value of `contest_id` in `contest.yaml`.
- `--watch`/`-w`: Continuously compile the pdf whenever a `solution.en.tex` changes. Note that this does not pick up changes to `*.yaml` configuration files. Note that this implies `--cp`.
- `--open <program>`/`-o <program>`: Open the continuously compiled pdf (with a specified program).
- `--web`: Build a web version of the pdf. This uses [contest-web.tex](../latex/contest-web.tex) instead of [contest.tex](../latex/contest.text) and [solutions-web.tex](../latex/solutions-web.tex) instead of [solutions.tex](../latex/solutions.tex). In practice, the only thing this does is to remove empty _this is not a blank page_ pages.
- `-1`: Run the LaTeX compiler only once.

## `problem_slides`

Renders a pdf with problem slides for the current problem or contest. The pdf is written to `problem-slide.en.pdf` or `problem-slides.en.pdf` respectively, and is a symlink to the generated pdf which is in a temporary directory.
See the [Implementation notes](implementation_notes.md#building-latex-files) for more.

**Flags**

- `--cp`: Instead of symlinking the final pdf, copy it into the contest directory.
- `--watch`/`-w`: Continuously compile the pdf whenever a `problem-slide.en.tex` changes. Note that this does not pick up changes to `*.yaml` configuration files. Note that this implies `--cp`.
- `--open <program>`/`-o <program>`: Open the continuously compiled pdf (with a specified program).
- `-1`: Run the LaTeX compiler only once.

## `stats`

`bt stats` prints a table of statistics for the current problem or the problems in the current contest.
This table contains:

- The problem label and shortname.
- Whether `problem.yaml` and `domjudge.ini` are found.
- Whether `statement/problem.en.tex` and `solution/solution.en.tex` are found.
- Whether the problem has any `input_validators` and `output_validators`.
- The number of `sample` and `secret` testcases.
- The number of `accepted`, `wrong_answer`, and `time_limit_exceeded` solutions.
- The number of C(++), Python 3, Java, and Kotlin solutions.
- An optional comment, as specified by the `comment:` field in `problem.yaml`.
- When `verified:` is set to `true` in `problem.yaml`, the comment will be shown in green.

This may look like:

```
problem               time yaml tex sol   val: I A O    sample secret bad    AC  WA TLE subs   cpp py java kt   comment
A appealtotheaudience  1.0    Y   Y   N        Y Y           2     30   0     4   4   2   10     2  1    1  0
```

`bt stats --all` additionally prints statistics about submissions, testcases, and git usage.

## `fuzz`

Use the `fuzz` command to test all accepted submissions against random test
data. Test data is generated by randomizing the `{seed}` in `generators.yaml`
rules which depend on it.

When a solution fails on a generated testcase, a generator invocation for the test is
stored in `generators.yaml` corresponding to `data/fuzz/<id>.in`.

**Flags**

- `[<testcases>]`: The generator invocations to use for generating random test data. Accepts directories (`data/secret`), test case names (`data/secret/1`), or test case files (`data/secret/1.in`).
- `--time <seconds>`/`-t <seconds>`: For how long to run the fuzzer.
- `--timeout <seconds>`: Override the default timeout for generators (`30s`).

# Problem validation

## `validate`

Use `bt validate --input [<testcases>]` to validate the `.in` files for the given testcases, or all testcases when not specified.

See `run <testcases>` for a description of how to pass testcases.

`bt validate --answer <testcases>` is similar to `bt validate --input` but validates `.ans` files instead of `.in` files.

`bt validate --invalid <invalid_testcases>` checks invalid test cases in `data/invalid_*`.

`bt validate --valid-output <valid_testcases>` checks valid test cases in `data/valid_output`.

`bt validate --generic <type>` automatically generates generic (in)valid test cases (like those in `data/valid_output` or `data/invalid_*`) and checks them. `dir` must be one of `valid_input`, `valid_answer`, `valid_output`, or `valid_output`

`bt validate` runs all of the above.

It supports the following flags when run for a single problem:

- `[testcases]`: a list of testcases and/or directories to validate. See `run <testcases>` for allowed formats. When not set, all testcases are validated.
- `--remove`: when passed, all invalid testcases are deleted.
- `--move-to <directory>`: when passed, all invalid testcases are moved to the given directory.
- `--no-testcase-sanity-checks`: when passed, all sanity checks on the testcases are skipped. You might want to set this in `.bapctools.yaml`.

## `constraints`

`bt constraints` has two purposes:

1. Verify that the bounds in the input/output validators match the bounds in the testcases.
2. Verify that the bounds in the problem statement match the bounds in the input/output validators.

See the [implementation notes](implementation_notes.md#constraints-checking) for more info.

**Verify testcase**

Validators that accept the `--constraints_file <path>` option are run on all testcases to check whether the bounds specified in the validator are actually reached by the test data. A warning is raised when this is not the case.
E.g. when an `input_validator` based on [headers/validation.h](../headers/validation.h) does `v.read_integer("n", 1, 1000)` (on line `7`) and the maximum value of `n` over all testcases is `999`, the following warning will be raised:

```
WARNING: BOUND NOT REACHED: The value at input_validator.cpp:7 was never equal to the upper bound of 1000. Max value found: 999
```

**Verify problem statement**

The command also runs some regexes over the input validator, output validator, and LaTeX sources to look for numeric bounds. These are then displayed next to each other to make it easy to **manually verify** that the bounds used in the statement match the bounds used in the validators.

This output will look like:

```
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

## `check_testing_tool`

`bt check_testing_tool` tries to run the testing tool with some submissions to ensure that it works properly.
However, this tool has many caveats and should never replace a carefull manual review of the testing tool.

**Caveats**
- the testing tool must be found under `attachments/testing_tool.<ext>`
- the testing tool must be callable as `{program} -f {in_path} {submission program}`
- the testing tool must accept the downloadable samples as well as files matching `data/testing_tool_test/*.in` as input files
- the testing tool must exits with a non zero exit code if something goes wrong
- the testing tool must not change the working directory

**Flags**

- `--timeout <seconds>`: Override the default timeout.
- `--all`/`-a`: run all testcases and don't stop after first error
- `--no-generate`/`-G`: Do not generate testcases before running. This usually won't be needed since checking that generated testcases are up to date is fast.

# Creating a new contest/problem

## `new_contest`

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
subtitle: The Northwestern European Programming Contest 2020
dirname (nwerc2020):
author (The NWERC 2020 jury):
test session? (y/N): n
year (2020):
source url: 2020.nwerc.eu
license (cc by-sa):
rights owner (if left empty, defaults to problem author):
```

## `new_problem`

Create a new problem directory and fill it with skel files. If `problems.yaml` is present, also add the problem to it. Information can be passed in either interactively or via command line arguments:

```
~nwerc2020 % bt new_problem
problem name (en): Test Problem
dirname (testproblem):
author: Ragnar Groot Koerkamp
type (pass-fail):
source (NWERC 2020):
source url (2020.nwerc.eu):
license (cc by-sa):
rights owner (if left empty, defaults to problem author):
LOG: Copying /home/philae/git/bapc/BAPCtools/skel/problem to testproblem.
```

```
~nwerc2020 % bt new_problem 'Test Problem 2' --author 'Ragnar Groot Koerkamp' --type interactive
LOG: Copying /home/philae/git/bapc/BAPCtools/skel/problem to testproblem2.
```

Files are usually copied from [skel/problem](../skel/problem), but this can be overridden as follows:

- If the `--skel <directory>` flag is specified, that directory is used instead.
- If either the current (contest) directory or the parent directory contains a `skel/problem` directory, that is used instead. This can be used to override the default problem template on a per-contest basis.

**Flags**

- `[<problem name>]`: The name of the problem. Will be asked interactively if not specified.
- `--author`: The author of the problem. Will be asked interactively if not specified.
- `--type`: The problem type to use. Must be one of `pass-fail`, `float`, `custom`, `interactive`, `multi-pass`, or `interactive multi-pass`.
- `--defaults`: Assume the defaults for fields not passed as arguments. This skips input-prompts but fails when defaults cannot be assumed.

## `skel`

Copy the given directory from [../skel/problem](../skel/problem) to the current problem directory. Directories passed must be relative to the problem root, e.g. `generators` or `output_validators/output_validator`.
The skel directory is found as with the `new_problem` command and can be overridden using `--skel`.

## `rename_problem`

Rename a problem, including its problem directory. If `problems.yaml` is present, also rename the problem in this file.
For multilingual problmems, asks for problem names in all languages;
the default problem directory name is based on the English problem name (if present.)
Do not forget to pass a `--problem` to rename when running this from a contest directory.

**Flags**

- `[<problem name>]`: The new name of the problem. Will be asked interactively if not specified.

## `gitlabci`

`bt gitlabici` prints configuration for Gitlab Continuous Integration to the terminal. This can be piped into the `.gitlab-ci.yml` file in the root of the repository. When there are multiple contests, just append the `bt gitlabci` of each of them, but deduplicate the top level `image:` and `default:` keys.

Use the `--latest-bt` flag to pull the latest version of BAPCtools before each
run. By default, the version in the docker image is used.

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
      - nwerc2020/testproblem/statement/**/*

  artifacts:
    expire_in: 1 week
    paths:
      - nwerc2020/solution*.pdf
      - nwerc2020/contest*.pdf

verify_testproblem:
  script:
      - ./bt all --cp --no-bar --problem nwerc2020/testproblem
  only:
    changes:
      - nwerc2020/testproblem/**/*
  artifacts:
    expire_in: 1 week
    paths:
      - nwerc2020/testproblem/problem*.pdf
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

## `forgejo_actions`

`bt forgejo_actions` writes Forgejo Actions workflows for the current contest to
the `.forgejo` directory in the root of the git repository.
When there are multiple contests, run `bt forgejo_actions` once for each
contest (either in the contest directory, or by passing `--contest <contest>`).

Use the `--latest-bt` flag to pull the latest version of BAPCtools before each
run. By default, the version in the docker image is used.

The generated workflows are similar to those for `bt gitlabci` described above.

For smooth operation, use the following in the forgejo runner `config.yaml` to
increase the memory limit of the container and mount `/tmp` to memory.
```
container:
  options: --memory=4g --memory-swap=4g --tmpfs /tmp:exec
```
and use the following label in `.runner`:
```json
{
  "labels": [
    "bapctools-docker:docker://ragnargrootkoerkamp/bapctools"
  ]
}
```

## `github_actions`

`bt github_actions` writes Github Actions workflows for the current contest to
the `.github` directory in the root of the git repository.
When there are multiple contests, run `bt github_actions` once for each
contest (either in the contest directory, or by passing `--contest <contest>`).

The generated workflows are similar to those for `bt gitlabci` described above.

# Exporting

## `samplezip`

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
...
```

## `zip`

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
- `--no-generate`/`-G`: Skip generation of testcases. This usually won't be needed since checking that generated testcases are up to date is fast.
- `--no-solutions`: Do not build solution slides for the contest zip.
- `--kattis`: Differences for Kattis export are:
  - Problems zips are written to `<shortname>.zip` instead of `<problemlabel>.zip`.
  - Kattis doesn't use a contest pdf, solution slides, and `contest/samples.zip`.
  - The contest level zip is written to `contest/<contest>-kattis.zip`
  - Kattis needs the `input_validators` directory, while DOMjudge doesn't use this.
  - Kattis problem zips get an additional top level directory named after the problem shortname.
  - _Statements_: Kattis’s problemtools builds statement HTML (and PDF) using `problem2html` (and `problem2pdf`) rather than `bt pdf`. Problem authors should check the resulting statements after exporting to Kattis; pay attention to:
    - The command `bt zip --kattis` exports `{statement,solution}/*` but not its subdirectories, so make sure illustrations and `\input`-ed tex sources are included.
    - Proper images scaling in the HTML output requires explict widths, such as `\includegraphics[width=.5\textwidth]{foo.png}`.

## `export`

This command uploads the `contest.yaml`, `problems.yaml`, and problem zips to DOMjudge.
Make sure to run the [`bt zip`](#zip) command before exporting, this does not happen automatically.

When run for a single problem, `contest.yaml` and `problems.yaml` are uploaded for the entire contest, but only the zip for the selected problem is uploaded.

# Misc

## `all`

This is a convenience command (mostly for use in CI) that runs the following subcommands in sequence for the current problem or each problem in the current contest:

- Build the problem pdf.
- Generate testcases, and check they are generated deterministically
- Validate input
- Validate output
- Run all submissions

This supports the `--cp` and `--no-time-limit` flags which are described under the `pdf` subcommand and the `--no-testcase-sanity-checks` flag from `validate`.

## `solve_stats`

Generates solve statistics that can be used in the solution presentation.
This command uses Matplotlib to generate one PDF for every problem (shown in the top-right of the slide),
one PDF for the language statistics (optionally included in `solution_footer.tex`),
and one TeX file that provides the data for the `\solvestats` command.

This command uses the `/teams?public=1` API endpoint of DOMjudge, so all teams on the public scoreboard are included (including spectator/company teams).

**Flags**

- `--contest-id`: Contest ID to use when reading from the API. Defaults to value of `contest_id` in `contest.yaml`.
- `--post-freeze`: When given, the solve stats will include submissions from after the scoreboard freeze.

## `sort`

Prints a list of all problems in the current contest (or single problem), together with their letter/ID:

```
~bapc % bt sort
A : appealtotheaudience
B : breakingbranches
...
```

## `update_problems_yaml`

`bt update_problems_yaml` updates the `problems.yaml` file of the contest.
This file should contain a list of problems, with for every problem the keys `id`, `label`, `name`, `rgb`, and `time_limit`.

**Flags**

- `--colors`: Apply the given list of colors to the list of problems, in the same order as in `problems.yaml`.
  Should be a comma-separated list of colors (hash-sign is optional), e.g.: `--colors ff0000,00ff00,0000ff`.
- `--sort`: Sort the problems in `problems.yaml` and re-label them starting from `A` (or `X` if `contest.yaml` contains `test_session: True`).

## `upgrade`

`bt upgrade` upgrades a problem from problem format version [`legacy`](https://icpc.io/problem-package-format/spec/legacy.html)
to [`2025-09`](https://icpc.io/problem-package-format/spec/2025-09.html).

## `tmp`

`bt tmp` prints the temporary directory that's used for all compilation output, run results, etc for the current problem or contest:

```
~bapc/findmyfamily % bt tmp
/tmp/bapctools_ef27b4/findmyfamily
```

This is useful for development/debugging in combination with `cd`:

```
cd `bt tmp`
```

**Flags**

- `--clean`: deletes the entire temporary (cache) directory for the current problem/contest.
