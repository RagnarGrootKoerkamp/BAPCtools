# Workflow
This documents aims to show the typical workflow of preparing a problem with BAPCtools and might be useful as a guide.
We start with the creation of a new problem and end after uploading it to DOMjudge.
Along the way, all commands that are used for various stages of problem preparaion are explained.

## Problem Directory
To specify a problem, we need the right directory structure:
<details>
<summary><strong>Directory structure</strong></summary>

	Problem
	├── answer_validators
	│   └── answer_validator
	├── data
	│   ├── sample
	│   └── secret
	├── generators (optional)
	│   └── generators.yaml
	├── input_validators
	│   └── input_validator
	├── output_validator
	├── solution
	│   └── solution.<lang>.tex
	├── statement
	│   └── problem.<lang>.tex
	├── submissions
	│   ├── accepted
	│   ├── run_time_error
	│   ├── time_limit_exceeded
	│   └── wrong_answer
	└── problem.yaml

</details>

The directory structure of a problem can be created with this command:
<details>
<summary><strong><samp>bt new_problem</samp></strong></summary>
This command will generate a new problem in a subdirectory of the current directory, including example files and <samp>problem.yaml</samp> with sensible defaults.
This command will request some information from you:
<ul>
	<li><strong>problem name (en):</strong> the problem name, in English</li>
	<li><strong>dirname:</strong> the name of the subdirectory (must have only lowercase letters in [a-z])</li>
	<li><strong>author:</strong> your name</li>
	<li><strong>validation type:</strong></li>
	<ul>
		<li><strong>default:</strong> compare output per token (ignoring case and whitespace changes)</li>
		<li><strong>float:</strong> same as default, but compare numbers with an epsilon (default: 10<sup>-6</sup>)</li>
		<li><strong>custom:</strong> your own output validator</li>
        <li><strong>interactive:</strong> an interactive problem (has a custom output validator)</li>
        <li><strong>multi-pass:</strong> a multi-pass problem (has a custom output validator)</li>
        <li><strong>interactive multi-pass:</strong> an interactive multi-pass problem (has a custom output validator)</li>
	</ul>
	<li><strong>source:</strong> typically, the contest name (optional)</li>
	<li><strong>source url:</strong> typically, a link to the contest (optional)</li>
	<li><strong>license:</strong> the license, we encourage to make problems public (cc by-sa)</li>
	<li><strong>rights owner:</strong> owner of the copyright (if this is not provided, the author is the rights owner)</li>
</ul>
For more information regarding these options and their meaning, you can also look at: <a href="https://icpc.io/problem-package-format/spec/2023-07-draft.html#problem-metadata">problem metadata</a>.
</details>

## Overview
For any problem and any stage of preparation, it is useful to get an overview of the current state of the problem.
BAPCtools offers two commands to offer such an overview.

The first one is `bt stats`. This shows a summary of files and programs that have been added to the problem:
<details>
<summary><strong><samp>bt stats</samp></strong></summary>
The output should look similiar tho this:

    problem    time yaml tex sol   val: I A O   sample secret bad good    AC  WA TLE subs   c(++) py java kt    comment
    A <name>    1.0    Y   0   0        N N          0      0   0    0     0   0   0    0       0  0    0  0
    -------------------------------------------------------------------------------------------------------------------
    TOTAL       1.0    1   0   0        0 0 0        0      0   0    0     0   0   0    0       0  0    0  0

Most of the columns should be self explanatory, but here is a description of what is displayed:
<ul>
	<li><strong>problem:</strong> the problem label followed by the problem directory name</li>
	<li><strong>time:</strong> the time limit in seconds</li>
	<li><strong>yaml:</strong> <samp>Y</samp> if <samp>problem.yaml</samp> exists (should always be true)</li>
	<li><strong>tex:</strong> the number of (LaTeX) problem statement languages</li>
	<li><strong>sol:</strong> the number of (LaTeX) solution slide languages</li>
	<li><strong>val I:</strong> <samp>Y</samp> if at least one input validator was found</li>
	<li><strong>val A:</strong> <samp>Y</samp> if at least one answer validator was found (note that interactive and multi-pass problems do not need such a validator)</li>
	<li><strong>val O:</strong> <samp>Y</samp> if the output validator was found (note that this must exist if the problem is interactive and/or multi-pass)</li>
	<li><strong>sample:</strong> the number of sample test cases (BAPCtools encourages to give at least two examples)</li>
	<li><strong>secret:</strong> the number of secret test cases (BAPCtools encourages to use 30-100 test cases)</li>
	<li><strong>bad:</strong> the number of invalid test cases (those test cases are intentionally wrong to check that the validator correctly rejects them)</li>
	<li><strong>AC, WA, TLE:</strong> the number of submissions in the corresponding <samp>accepted</samp>, <samp>time_limit_exceeded</samp>, and <samp>wrong_answer</samp> directories</li>
	<li><strong>subs:</strong> The total number of submissions (files) in the <samp>submissions/</samp> directory</li>
	<li><strong>c(++), py, java, kt:</strong> the number of <it>accpeted</it> submissions in the corresponding languages</li>
	<li><strong>comment:</strong> the content of the <samp>comment</samp> entry in <samp>problem.yaml</samp></li>
</ul>
</details>

A more detailed overview of the submissions and test cases can be gathered with `bt run -o -a`:
<details>
<summary><strong><samp>bt run -o -a[a] [submissions/...] [data/...]</samp></strong></summary>
<ul>
	<li><strong>-o:</strong> print an overview table (if possible, with live updates)</li>
	<li><strong>-a:</strong> disable lazy judging for WA submissions</li>
	<li><strong>-aa:</strong> completely disable lazy judging</li>
	<li><strong>[submissions/...]:</strong> a list of directories/submissions to run</li>
	<li><strong>[data/...]:</strong> a list of directories/test cases to run</li>
</ul>
A more detailed description of <samp>bt run</samp> will follow in the next section.
After running all selected submissions on all selected test cases, the output should look similiar to this:

	accepted/solution.py:          aaaAAAAAAA AAAAAAA
	wrong_answer/wrong.py:         aaaAAWAAAW WAAAAAA
	time_limit_exceeded/brute.cpp: aaaAAAAATT TT-----
	run_time_error/bug.java:       aaaAARA--- -------

Each row represents a submission, each column represents a test case.
To make the table easier to read, the test cases are grouped in multiples of 10 and samples are marked with a lowercase letter.

The entries correspond to the verdict that a submission got on a test case:
<ul>
	<li><strong>A:</strong> accepted</li>
	<li><strong>W:</strong> wrong answer</li>
	<li><strong>T:</strong> time limit exceeded</li>
	<li><strong>R:</strong> run time error</li>
	<li><strong>-:</strong> skipped because of lazy judging</li>
</ul>
</details>

## Problem Preparation
Every problem needs the following things:
 - submissions
 - test cases/generators
 - validators
 - a problem statement

The order in which you add these things is up to you.
However, this guide will use the mentioned order.

### Submissions
Strictly speaking, only one accepted submission is really required.
However, multiple accepted submission in various languages help determining a good time limit.
Additionally, adding WA submissions and TLE submissions help improving the test cases and the time limit, respectively.

The following commands can be used to run a submission:
<details>
<summary><strong><samp>bt test submissions/... [data/...|-i]</samp></strong></summary>
This command will run the selected submission on a given input.
As input to the submission, you can either specify a test case/directory in <samp>data/</samp>,
or you can run the program in interactive mode with <samp>-i</samp>, in which case the console input is passed to the submission.
After running the submission, its output and running time is printed.

Note that the output is only printed, it is <strong>not</strong> checked for correctness!
</details>

<details>
<summary><strong><samp>bt run [-G] [submissions/...] [data/...]</samp></strong></summary>
This command will run the selected submission on a given test case.
This will also verify the output of the submission but will not display the output.

If <samp>-G</samp> (a shortcut for <samp>--no-generate</samp>) is given, the data directory is used as-is, without changing any files.
If <samp>-G</samp> is not given, the data directory will be regenerated first, see [Test cases/Generators](#testcasesgenerators) for more information.
</details>

### Test cases/Generators
 - [output validator]
 - `bt generate`

### Input and Answer Validators
 - `bt validate`

### Output Validators

### Statement and Solution
 - `bt pdf`
 - `bt solutions`

## Finalize
 - `bt time_limit`
 - `bt fuzz`
 - `bt generate --reorder`
 - `bt constraints`
 - `bt validate`
 - `bt stats --more`

## Upload
 - `bt zip`
 - `bt samplezip`
 - `bt export`
