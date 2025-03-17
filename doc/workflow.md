# Workflow
This documents aims to show the typical workflow of preparing a problem with BAPCtools and might be usefull as a guide.
We start with the creation of a new problem and end after uploading it to DOMjudge.
Along the way all commands that are used for various stages of problem preparaion are explained.

## Problem Directory
To specify a problem we need the right directory structure:
<details>
<summary><strong>Directory</strong></summary>

	Problem
	├── data
	│   ├── sample
	│   └── secret
	├── generators (optional)
	│   └── generator.yaml
	├── input_validators
	├── problem_statement
	│   ├── problem.<lang>.tex
	│   ├── solution.<lang>.tex
	├── output_validators
	│   └── output_validator
	├── submissions
	│   ├── accepted
	│   ├── run_time_error
	│   ├── time_limit_exceeded
	│   └── wrong_answer
	└── problem.yaml

</details>

Luckily all of this can be created with a single command:
<details>
<summary><strong><samp>bt new_problem</samp></strong></summary>
This command will generate a new problem in a sub-directory of the current directory and will also add example files and populates the <samp>problem.yaml</samp> with sensible defaults.
However, first the command will request some additional information from you:
<ul>
	<li><strong>problem name (en):</strong> the problem name in english</li>
	<li><strong>dirname:</strong> the name of the subdirectory (letters in [a-zA-Z] preferred)</li>
	<li><strong>author:</strong> your name</li>
	<li><strong>validation type:</strong></li>
	<ul>
		<li><strong>default:</strong> compare output tokenwise (ignoring case and whitespace changes)</li>
		<li><strong>float:</strong> same as default but compare integers and floats with an epsilon (default: 10<sup>-6</sup>)</li>
		<li><strong>custom:</strong> your own output validator</li>
			<ul>
				<li><strong>interactive:</strong> yes or no (default: no)</li>
				<li><strong>multipass:</strong> yes or no (default: no)</li>
			</ul>
	</ul>
	<li><strong>source:</strong> typically the contest name (optional)</li>
	<li><strong>source url:</strong> typically a link to the contest (optional)</li>
	<li><strong>license:</strong> the license, we encourage to make problems public (cc by-sa)</li>
	<li><strong>rights owner:</strong> owner of the copyright (default: author)</li>
</ul>
For more information regarding these options and their meaning you can also look at: <a href="https://github.com/Kattis/problem-package-format/blob/master/spec/legacy-icpc.md#problem-metadata">problem metadata</a>.
</details>

## Overview
For any problem and any stage of preparation it is useful to get an overview of the current state of the problem.
BAPCtools offers two commands to offer such an overview.

The first one is `bt stats` and shows a summary of files and programs that have been added to the problem:
<details>
<summary><strong><samp>bt stats</samp></strong></summary>
The output should look similiar tho this:

	problem   time yaml tex sol   val: I A O   sample secret bad    AC  WA TLE subs   c(++) py java kt    comment
	A <name>   1.0    Y   0   0        N N          0      0   6     0   0   0    0       0  0    0  0
	-------------------------------------------------------------------------------------------------------------
	TOTAL      1.0    1   0   0        0 0 0        0      0   6     0   0   0    0       0  0    0  0

At the first blink most of the columns should be self explanatory.
Non the less description of what gets displayed might be useful:
<ul>
	<li><strong>problem:</strong> the problem label followed by the problem directory name</li>
	<li><strong>time:</strong> the timelimit in seconds</li>
	<li><strong>yaml:</strong> <samp>Y</samp> if the <samp>problem.yaml</samp> exists (should always be true)</li>
	<li><strong>tex:</strong> the number of (latex) problem statements</li>
	<li><strong>sol:</strong> the number of (latex) solution slides</li>
	<li><strong>val I:</strong> <samp>Y</samp> if at least one input validator was found</li>
	<li><strong>val A:</strong> <samp>Y</samp> if at least one answer validator was found (note that interactive and multipass problems never need such a validator)</li>
	<li><strong>val O:</strong> <samp>Y</samp> if the output validator was found (note that this should exists if and only if the validation type is <it>custom</it>)</li>
	<li><strong>sample:</strong> the number of sample testcases (BAPCtools encourages to give at least two examples)</li>
	<li><strong>secret:</strong> the number of secret testcases (BAPCtools encourages to use 30-100 testcases)</li>
	<li><strong>bad:</strong> the number of invalid testcases (those testcases are intentionally wrong to check validator behaviour)</li>
	<li><strong>AC, WA, TLE:</strong> the number of submissions in the corresponsing submission folders <samp>accepted</samp>, <samp>time_limit_exceeded</samp>, and <samp>wrong_answer</samp></li>
	<li><strong>subs:</strong> The total number of submissions (files) in the submissions directory</li>
	<li><strong>c(++), py, java, kt:</strong> the number of <it>accpeted</it> submissions in the corresponding language</li>
	<li><strong>comment:</strong> the content of the <samp>comment</samp> entry in the <samp>problem.yaml</samp></li>
</ul>
</details>

 Additional stats about submissions/testcases can be gathered with `bt run` and the right combination of output parameters:
 <details>
<summary><strong><samp>bt run -o -a[a] [submissions/...] [data/...]</samp></strong></summary>
<ul>
	<li><strong>-o:</strong> print an overview table (if possible with live updates)</li>
	<li><strong>-a:</strong> disable lazy judging for WA submission</li>
	<li><strong>-aa:</strong> completely disable lazy judging</li>
	<li><strong>[submissions/...]:</strong> a list of directories/submissions to run</li>
	<li><strong>[data/...]:</strong> a list of directories/testcases to run</li>
</ul>
A more detailed description of <samp>bt run</samp> will follow in the next section.
After running all selected submissions on all selected testcases the output should look similiar to this:

	accepted/sol.py:               aaaAAAAAAA AAAAAAA
	wrong_answer/wa.py:            aaaAAWAAAW WAAAAAA
	time_limit_exceeded/brute.cpp: aaaAAAAATT TT-----
	run_time_error/bug.java:       aaaAARA--- -------

Each row represents a submission, each column represents a testcase.
To make the table easier to read the testcases are grouped in multiples of 10 and samples are marked with a lowercase letter.

The entries correspond to the verdict that a submission got on a testcase:
<ul>
	<li><strong>A:</strong> accepted</li>
	<li><strong>W:</strong> wrong answer</li>
	<li><strong>T:</strong> time limit exceeded</li>
	<li><strong>R:</strong> runtime error</li>
	<li><strong>-:</strong> skipped because of lazy judging</li>
</ul>
</details>

## Problem Preparation
Every problem needs the following things:
 - submissions
 - testcases/generators
 - validators
 - a statement

In which order you add these things is up to you.
However, this guide will use the mentioned order.

### Submissions
Strictly speaking only one accepted submission is really required.
However, multiple accepted submission in various languages help determining a good timelimit.
And even wrong answer submission and timelimit submissions can help improving the timelimit and testcases.

The following commands help us writing any kind of submission:
<details>
<summary><strong><samp>bt test [submissions/...] [data/...|-i]</samp></strong></summary>
This command will run the selected submission on a given input.
As input you can either specify a testcase/directory in <samp>/data/</samp>.
Or you can run the program in interactive mode with <samp>-i</samp> in which case the console input is passed to the submission.
In both cases the submission output and required time is printed.

Note that the output is only printed <strong>not</strong> checked!
</details>

<details>
<summary><strong><samp>bt run [-G] [submissions/...] [data/...]</samp></strong></summary>
This command will run the selected submission on a given testcase.
This will also verify the output of the submission but will not display the output.

If <strong>-G</strong> is given the data directory is used as without changing any files.
If <strong>-G</strong> is not given the data directory will be brought up do date first, see [Testcases/Generators](#testcasesgenerators) for more information.
</details>

### Testcases/Generators
 - [output validator]
 - `bt generate`

### Input and Answer Validators
 - `bt validate`

### Output Validators

### Statement and Solution
 - `bt pdf`
 - `bt solutions`

## Finalize
 - `bt timelimit`
 - `bt fuzz`
 - `bt generate --reorder`
 - `bt constraints`
 - `bt validate`
 - `bt stats --more`

## Upload
 - `bt zip`
 - `bt samplezip`
 - `bt export`
