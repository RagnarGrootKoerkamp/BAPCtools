# Documentation for subcommands

This document explains all subcommands and their flags, sorted per category.

## Global flags

The flags below work for any subcommand:

* `--contest <directory>`: The directory of the contest to use, if not the current directory. At most one of `--contest` and `--problem` may be used. Useful in CI jobs.
* `--problem <directory>`: The directory of the problem to use, if not the current directory. At most one of `--contest` and `--problem` may be used. Useful in CI jobs.
* `--no-bar`: Disable showing progress bars. This is useful when running in non-interactive contexts (such as CI jobs) or on platforms/terminals that don't handle the progress bars well.
* `--error`/`-e`: show full output of failing commands using `--error`. The default is to show a short snippet only.
* `--cpp_flags`: Additional flags to pass to any C++ compilation rule. Useful for e.g. `--cpp_flags=-fsanitize=undefined`.
* `--force_build`: Force rebuilding binaries instead of reusing cached version.

## Problem development

### `run`
### `test`
### `generate`
### `clean`
### `pdf`
### `solutions`
### `stats`

## Problem validation

### `input`
### `output`
### `validate`

`bt validate` is a convenience command that validates both input and output files. It supports the following flags:

- `testcases`: a list of testcases and/or directories to validate.
- `--remove`: when passed, all invalid testcases are deleted.
- `--movo_to <directory>`: when passed, all invalid testcases are moved to the given directory.

### `constraints`

Validators based on [headers/validation.h](../headers/validation.h)

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
~nwerc2020 % bt new_problem 'Test Problem 2' --author 'Ragnar Groot Koerkamp' --validation_interactive
LOG: Copying /home/philae/git/bapc/BAPCtools/skel/problem to testproblem2.
```

Files are usually copied from [skel/problem](../skel/problem), but this can be overridden as follows:

- If the `--skel <directory>` flag is specified, that directory is used instead.
- If either the current (contest) directory or the parent directory contains a `skel/problem` directory, that is used instead. This can be used to override the default problem template on a per-contest basis.

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

**Flags**:
- `--skip`: Do not rebuild problem zips when building a contest zip.
- `--force`/`-f`: Skip validating input and output. This is useful to speed up regenerating the zip with only minimal changes.
- `--no_solutions`: Do not build solution slides for the contest zip.
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

This supports the `--cp` and `--no_timelimit` flags which are described under the `pdf` subcommand.


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
