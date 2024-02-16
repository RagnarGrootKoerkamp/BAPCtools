# Validation

BAPCtools distinguishes 3 types of validation, one more than the [problem package format specification](https://www.kattis.com/problem-package-format/spec/problem_package_format#input-validators):

1. input validation, which validates the `.in` file for every test case, typically for syntax, format, correctness, and range,
2. answer validation, which validates the `.ans` file for every test case, typically for syntax, format, and ranges, but not for correctness,
3. output validation, which checks correctness and running time for the output of every submission.

Input and answer validation run on the _files_ in `data/*`; their purpose is to ensure problem quality.
Output validation runs on the output of the author submissions in `submissions` (and eventually on solver submissions when the problem is hosted on a judge system);
the purpose of output validation is to check correctness of _submissions_.

The testcases in `/data/sample` and `/data/secret` must pass both input, answer, and output validation;
whereas submission output most pass output validation.


## Common parameters/settings

These are some things that hold for all types of validation mentioned below.

- For each testcase, all validators of the same type are run in lexicographic order. If one
  fails, later ones are skipped.
- In BAPCtools, the current working directory is always a temporary
  `<testcase>.feedbackdir` directory.
- In BAPCtools, `/path/to/feedbackdir` is simply the path of the current
  working directory. For `output validation`, you can write e.g. files
  `judgemessage.txt`, `judgeerror.txt`, `teammessage.txt`, and `score.txt`.
  (BAPCtools only handles the first 2.)
- The return code must be `42` for successful validation.
- The return code must be `43` for failed validation. (Note that the spec is
  slightly more lenient and allows any non-`42` return code for input format
  validation. BAPCtools expects a code of exactly `43` when validating
  invalid testcases (see below).)
- For input and answer validation, the out-of-spec `--constraints-file
<path>` flag is set when running `bt constraints`. The validator can write some
  statistics on the testcase to this file. See the [implementation
  notes](implementation_notes.md#constraints-checking).
- `<{input,output}_validator_flags>` are either empty, or the value of the
  `{input,output}_validator_flags` key in the first `testdata.yaml` file that is found
  in the directory (testgroup) of the current testcase or its parents.

## Input validation

`bt validate --input`

Test if the testcase input file `testcase.in` file passes the 'input validators'. Each file or
directory in `/input_validators/` is an input validator.
Input validators receive the testcase on standard input, as

```
input_validator [input_validator_flags] < testcase.in
```

## Answer validation

`bt validate --answer`

BAPCtools allows (in fact, encourages) the validation of the `.ans`-file of each testcase.
As for input validation, every program in `answer_validators` is a validator, and all validators must pass.
Answer validators receive the testcase answer file on standard input, as
```
answer_validator /path/to/testcase.in [output_validator_flags] < testcase.ans
```

Answer validation can be as simple as checking that standard input contains a single integer (and nothing else).
A more advanced use case would be to read an integer `n` from the testcase input file `testcase.in` file provided as the first argument,
followed by verifying that the standard input contains `n` newline-separated integers.

All answer files are also checked with the output validator invoked as

```
output_validator /path/to/testcase.in /path/to/testcase.ans /path/to/feedbackdir \
    case_sensitive space_change_sensitive [output_validator_flags] < testcase.ans
```

In particular, note the flags `case_sensitive` and `space_change_sensitive`,
which allows an output validator to be more strict about the format of `.ans` files than about submission output.

## Invalid test cases

`bt validate --invalid`

BAPCtools expects deliberately invalid testcases in `data/invalid_{inputs, answers, outputs}`.
These ensure that validators reject under the expected circumstances.

### Invalid inputs

Invalid inputs are placed in `data/invalid_inputs` and consist only of an `.in`-file.
An invalid input must be rejected by at least one input validator.

Examples:

```yaml
"negative":
    in: "-1"
"too_large":
    in: "100"
"not_a_number:
    in: foo
"extra input":
    in: 0 1
"trailing whitespace":
    in: " 0"
```

### Invalid answers

Invalid answers are test cases in `data/invalid_answers`.
Such a test case consist of input and answer files (`.in` and `.ans`), just like a normal test case.
The input file must pass input validation (i.e., all input validators must accept).
The testcase must fail answer validation, i.e., at least one answer validator or the output validator must reject it.
The output validator is run in strict mode, i.e., with the flags `case_sensitive` and `space_change_sensitive`;
to ensure maximum conformity of answer files in the test data.

Examples:

```yaml
"negative":
    in: "0"
    ans: "-1"
"trailing whitespace":
    in: "0"
    ans: " 0"
```

### Invalid outputs

Invalid outputs are valid test cases in `data/invalid_output` with an additional `.out`-file that must fail output validation.
In particular, the input file must pass input validation, the answer file must pass answer validation.
However,  the `.out`-file must fail output validation for the test case.

Examples:
```yaml
"wrong_answer":
    in: "0"
    ans: "0"
    out: "1"
```

## Output validation

The output validator checks whether the output of a submission is correct.
Output validation receives submission output on standard input.
If `testcase.out` is the output produced by a submission on `testcase.in`,
the output validator is called as follows:

```
output_validator /path/to/testcase.in /path/to/testcase.ans /path/to/feedbackdir \
  [problem_yaml_flags] [output_validator_flags] \
  < testcase.out
```

- `[problem_yaml_flags]` is the value of `validator_flags` in `problem.yaml`.

When `output_validators` is empty (and `validation: default` in `problem.yaml`), the default output validator is used.

_Example_.
Suppose a problem requires as output some integer `x`, and then any two integers
that sum to `x`. Then, the output validator could first read `x` from the `.ans`
file (second argument), and compare that to the `x` given on `stdin`. Then, it
can read the remaining two integers on `stdin` and verify they sum to `x`.

### Custom ouput validation

When `validation: custom`, the program in `output_validators` is used as the output validator.


### Interactive problems

For interactive problems (`validation: custom interactive`), the invocation is
the same as above, but `stdin` is a pipe that feeds team output into the
validator instead of a file.
Similarly, `stdout` is connected to a pipe that forwards to the submission's `stdin`.
