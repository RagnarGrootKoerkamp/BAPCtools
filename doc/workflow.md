# Workflow
This document aims to show the typical workflow of preparing a problem with BAPCtools and might be useful as a guide.
We start with the creation of a new problem and end after uploading it to DOMjudge.
Along the way, all commands that are used for various stages of problem preparation are explained.

> [!CAUTION]
> Do not use BAPCtools on problem packages from untrusted sources.
> Programs are **not** run inside a sandbox.
> Malicious submissions, validators, visualizers, and generators can harm your system.

## Topics
- [Problem Directory](#problem-directory)
  - [Required Files](#required-files)
  - [Optional Files](#optional-files)
  - [`bt new_problem`](#bt-new_problem)
- [Overview](#overview)
  - [`bt stats`](#bt-stats)
  - [`bt run -oa[a]`](#bt-run--o--aa-submissions-data)
- [Problem Preparation](#problem-preparation)
  - [Submissions](#submissions)
  - [Test cases/Generators](#test-cases/generators)
  - [Input and Answer Validators](#input-and-answer-validators)
  - [Output Validators](#output-validators)
  - [Statement and Solution](#statement-and-solution)
- [Finalize](#finalize)
- [Upload](#upload)


## Problem Directory
A problem directory is specified by the existence of a `problem.yaml`.
However, to set up a proper problem, we need some more subdirectories and files.

#### Required Files
```ini
Problem
├─╴answer_validators/
│  └─╴...
├─╴data/
│  ├─╴sample/
│  └─╴secret/
├─╴input_validators/
│  └─╴...
├─╴output_validator/              ; for custom output checking
│  └─╴...
├─╴solution/
│  └─╴solution.<lang>.tex
├─╴statement/
│  └─╴problem.<lang>.tex
├─╴submissions/
│  ├─╴accepted/
│  ├─╴run_time_error/
│  ├─╴time_limit_exceeded/
│  └─╴wrong_answer/
└─╴problem.yaml
```
> [!IMPORTANT]
> There can be many input/answer validator*s* but only one output validator.
> Therefore, it is the only one of those directories that does not end with a plural *s*.
#### Optional Files
```ini
Problem
├─╴data/
│  ├─╴invalid_input/
│  ├─╴invalid_answer/
│  ├─╴invalid_output/
│  └─╴valid_output/
┆
├─╴generators/
│  ├─╴...
│  └─╴generators.yaml
├─╴input_visualizer/
│  └─╴...
└─╴output_visualizer/
   └─╴...
```

#### `bt new_problem`

This command will generate a new problem with the right structure.
The command will also generate some example files and write a `problem.yaml` with sensible defaults.
The command will request some information from you:

- **problem name (en):** the problem name, in English
- **dirname:** the name of the subdirectory that gets created (must have only lowercase letters in [a-z])
- **author:** your name
- **validation type:**
  - **default:** compare output per token (ignoring case and whitespace changes)
  - **float:** same as default, but compare numbers with an epsilon (default: 10<sup>-6</sup>)
  - **custom:** your own output validator (has a custom output validator)
  - **interactive:** an interactive problem (has a custom output validator)
  - **multi-pass:** a multi-pass problem (has a custom output validator)
  - **interactive multi-pass:** an interactive multi-pass problem (has a custom output validator)
- **source:** typically, the contest name (optional)
- **source url:** typically, a link to the contest (optional)
- **license:** the license, we encourage to make problems public (cc by-sa)
- **rights owner:** owner of the copyright (if this is not provided, the author is the rights owner)

> [!TIP]
> For more information regarding these options and their meaning, you can also look at the [problem specification](https://icpc.io/problem-package-format/spec/2025-09.html#problem-metadata).

## Overview
For any problem and any stage of preparation, it is useful to get an overview of the current state of the problem.
BAPCtools offers two commands to offer such an overview.

#### `bt stats`
This shows a summary of files and programs that have been added to the problem.
The output should look similar to this:
```ini
problem    time yaml tex sol   val: I A O   sample secret bad good    AC  WA TLE subs   c(++) py java kt    comment
A <name>    1.0    Y   0   0        N N          0      0   0    0     0   0   0    0       0  0    0  0
-------------------------------------------------------------------------------------------------------------------
TOTAL       1.0    1   0   0        0 0 0        0      0   0    0     0   0   0    0       0  0    0  0
```
Most of the columns should be self-explanatory, but here are descriptions of what is displayed:
- **problem:** the problem label followed by the problem directory name
- **time:** the time limit in seconds
- **yaml:** `Y` if `problem.yaml` exists (should always be true)
- **tex:** the number of (LaTeX) problem statement languages
- **sol:** the number of (LaTeX) solution slide languages
- **val I:** `Y` if at least one input validator was found
- **val A:** `Y` if at least one answer validator was found (note that interactive and multi-pass problems do not need such a validator)
- **val O:** `Y` if the output validator was found (note that this must exist if the problem is interactive and/or multi-pass)
- **sample:** the number of sample test cases (BAPCtools encourages to give at least two examples)
- **secret:** the number of secret test cases (BAPCtools encourages to use 30-100 test cases)
- **bad:** the number of invalid test cases (those test cases are intentionally wrong to check that the validators correctly reject them)
- **AC, WA, TLE:** the number of submissions in the corresponding `accepted`, `time_limit_exceeded`, and `wrong_answer` directories
- **subs:** The total number of submissions (files) in the `submissions/` directory
- **c(++), py, java, kt:** the number of *accepted* submissions in the corresponding language
- **comment:** the content of the `comment` entry in `problem.yaml`

#### `bt run -o -a[a] [submissions/...] [data/...]`
This command runs submissions and presents their verdict on the test cases.
The output should look similar to this:
```ini
accepted/solution.py:          aaaAAAAAAA AAAAAAA
wrong_answer/wrong.py:         aaaAAWAAAW WAAAAAA
time_limit_exceeded/brute.cpp: aaaAAAAATT TT-----
run_time_error/bug.java:       aaaAARA--- -------
```
Each row represents a submission, each column represents a test case.
To make the table easier to read, the test cases are grouped in multiples of 10 and samples are marked with a lowercase letter.

The entries correspond to the verdict that a submission got on a test case:
- **A:** accepted
- **W:** wrong answer
- **T:** time limit exceeded
- **R:** run time error
- **-:** skipped because of lazy judging

> [!NOTE]
> Here is a short explanation for the given command line parameters:
> - **-o:** enable the overview table (if possible, printed with live updates)
> - **-a:** disable lazy judging for WA/RTE submissions
> - **-aa:** completely disable lazy judging
> - **[submissions/...]:** a list of directories/submissions to run
> - **[data/...]:** a list of directories/test cases to use

## Problem Preparation
Every problem needs the following things:
- [Submissions](#submissions)
- [Test cases/Generators](#test-cases/generators)
- [Input and Answer Validators](#input-and-answer-validators)
- [Output Validators](#output-validators)
- [Statement and Solution](#statement-and-solution)

> [!TIP]
> The order in which you add these things is up to you.
> However, this guide will use the mentioned order.

### Submissions
---
Strictly speaking, only one accepted submission is really required.
However, multiple accepted submissions in various languages help determine a good time limit.
Additionally, adding WA submissions and TLE submissions helps improve the test cases and the time limit.

The following commands can be used to run a submission:

#### `bt test submissions/... [data/...|-i]`
This command will run the selected submission on a given input.
As input to the submission, you can either specify a test case/directory in `data/`,
or you can run the program in interactive mode with `-i`, in which case the console input is passed to the submission.
After running the submission, its output and running time is printed.

> [!IMPORTANT]
> Note that the output is only printed, it is **not** validated!

#### `bt run [-G] [submissions/...] [data/...]`
This command will run the selected submission on a given test case.
This will also validate the output of the submission but will not display the output.

> [!TIP]
> By default `bt run` will try to keep the `data/` directory up to date, see [Test cases/Generators](#test-cases/generators) for more information.
> If you just want to run the submission you can add `-G` (short for `--no-generate`) to disable this behaviour.

### Test cases/Generators
---
 - [output validator]
 - `bt generate`

### Input and Answer Validators
---
 - `bt validate`

### Output Validators
---

### Statement and Solution
---
 - `bt pdf`
 - `bt solutions`

## Finalize
---
 - `bt time_limit`
 - `bt fuzz`
 - `bt generate --reorder`
 - `bt constraints`
 - `bt validate`
 - `bt stats --all`

## Upload
---
 - `bt zip`
 - `bt samplezip`
 - `bt export`
