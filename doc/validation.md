# Validation

BAPCtools does 3 types of validation, one more than the spec (https://www.kattis.com/problem-package-format/spec/problem_package_format#input-validators):

1. input validation, which validates the `.in` file for every test case, typically for syntax, format, and ranges
2. answer validation, which validates the `.ans` file for every test case, typically for syntax, format, and ranges, but not for correctness
3. ouput validation, which checks correctness and running time for the output of every submission.

Input and answer validation run on the  _files_ in `data/*`; their purpose is to ensure problem quality.
Output validation runs on the output of the author submissions in `submission` (and eventually on solver submissions when the problem is hosted on a judge system);
the purpose of output validation is to check correctness of submitted problems.


## Common parameters/settings

These are some things that hold for all types of validation mentioned below.

- For each testcase, all validators in the same directory are run in lexicographic order. If one
  fails, later ones are skipped.
- In BAPCtools, the current working directory is always a temporary
  `<testcase>.feedbackdir` directory.
- In BAPCtools, `/path/to/feedbackdir` is simply the path of the current
  working directory. For `output validation`, you can write e.g. files
  `judgemessage.txt`, `judgeerror.txt`, `teammessage.txt`, and `score.txt`.
  (BAPCtools only handles the first 2.)
- The return code should be `42` for success/AC.
- The return code should be `43` for failure/WA. (Note that the spec is
  slightly more lenient and allows any non-`42` return code for input format
  validation. BAPCtools expects a code of exactly `43` when validating
  `data/invalid_inputs` testcases (see below).)
- For input and answer validation, the out-of-spec `--constraints-file
<path>` flag is set when running `bt constraints`. The validator can write some
  statistics on the testcase to this file. See the [implementation
  notes](implementation_notes.md#constraints-checking).
- `<{input,output}_validator_flags>` are either empty, or the value of the
  `{input,output}_validator_flags` key in the first `testdata.yaml` file that is found
  in the directory (testgroup) of the current testcase or its parents.

## Input validation

Test if the testcase input file `testcase.in` file passes the 'input validators'. Each file or
directory in `/input_validators/` is an input validator. 
Input validators receive the testcase on standard input, as

```
input_validator [input_validator_flags] < testcase.in
```

## Answer validation

BAPCtools allows (in fact, encourages) the validation of the `.ans`-file of each testcase.
As for input validatio, every program in `answer_validators` is a validator, and all validator must pass.
Answer validators receive the testcase answer file on standard input, as
```
answer_validator /path/to/testcase.in [output_validator_flags] < tc.ans
```

Answer validation can be as simple as checking that standard input contains a single integer (and nothing else).
A more advanced used would be to read `n` from the testcase input file `testcase.in` file provided as the first argument. 
Then read `n` lines from standard input and verify that they contain integers separated by newlines.

All answer files are also checked with the output validator invoked as

```
output_validator /path/to/testcase.in /path/to/testcase.ans /path/to/feedbackdir \
    case_sensitive space_change_sensitive [output_validator_flags] < testcase.ans
```

In particular, note the flags `case_sensitive` and `space_change_sensitive`, 
which allows an output validator to be less lenient about the format of `.ans` files than about submission output.

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


## `data/invalid_inputs` validation

BAPCtools allows testcases in `data/invalid_outputs` to test that validators fail on
specific types of input that do not follow the constraints. In
particular:

- If `data/invalid_inputs/<testcase>.in` is present, at least one input format validator must fail (return `43`).

## `data/invalid_outputs` validation (out-of-spec)

BAPCtools allows testcases in `data/invalid_outputs` to test that output-format
validators (for problems with default validation) fail on
specific types of output that do not follow the constraints. In
particular:

- If `data/invalid_outputs.{in,ans}` are both present, at least one output format validator must fail (return `43`).
