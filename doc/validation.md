# Validation

BAPCtools does 3 types of validation, one more than the spec (https://www.kattis.com/problem-package-format/spec/problem_package_format#input-validators):

## Common parameters/settings

These are some things that hold for all types of validation mentioned below.

- For each testcase, all validators are run in lexicographic order. If one
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
  `data/bad` testcases (see below).)
- For `input/output format validation`, the out-of-spec `--constraints-file
<path>` flag is set when running `bt constraints`. The validator can write some
  statistics on the testcase to this file. See the [implementation
  notes](implementation_notes.md#constraints-checking).
- `<{input,output}_validator_flags>` are either empty, or the value of the
  `{input,output}_validator_flags` key in the first `testdata.yaml` file that is found
  in the directory (testgroup) of the current testcase or its parents.

## Input format validation

Test if the `testcase.in` file passes the 'input validators'. Each file or
directory in `/input_validators/` is an input validator. Input
validators are called as

```
input_validator <input_validator_flags> [--contraints_file <path>] < <testcase>.in
```

- The testcase input is given on `stdin`.

## Output format validation (out-of-spec)

Normally output validators are only run on team/submission output to validate
if it correctly solves the testcase. `output format validation` additionally
verifies the `.ans` file in the repository:

- For `validation: default` problems, check the syntax of the `.ans` file.
- For `validation: custom` problems, validate the `.ans` file as if it was a
  team submission.
- For `validation: custom interactive`, this step is skipped, and the `.ans`
  file can contain anything. (Typically it's just an empty file.)

```
output_validator /path/to/testcase.in /path/to/testcase.ans /path/to/feedbackdir \
  case_sensitive space_change_sensitive <output_validator_flags> [--constraints_file <path>] \
  < <testcase>.ans
```

- The testcase answer to be validated is given on `stdin`.
- The `case_sensitive` and `space_change_sensitive` flags are passed, since
  it is nice for `.ans` files to _exactly_ follow the spec. (This is
  not necessarily a requirement for team submission output.)

**Example usage**

- Default validation (`validation: default`): Make sure the syntax of the
  `.ans` file passed on `stdin` is correct. This can be as simple as checking
  that `stdin` contains a single integer. Slightly more advanced would be read
  `n` from the `.in` file (first argument). Then read `n` lines from `stdin`
  and verify that they contain integers separated by newlines.
- Custom validation (`validation: custom`): Validate the `.ans` file on
  `stdin` as you would validate a team submission. This assumes that the
  `.ans` file in indeed present in the `data/` directory and a valid solution
  to the problem. While this is not technically required otherwise, this has
  never been false not the case. See 'output validation' below for an example.

## Output validation

**Custom validation**
When `validation: custom`, the output validation checks whether the output of a
team submission is correct.

```
output_validator /path/to/testcase.in /path/to/testcase.ans /path/to/feedbackdir \
  <problem_yaml_flags> <output_validator_flags> \
  < team_output
```

- `<problem_yaml_flags>` is the value of `validator_flags` in `problem.yaml`.

- Team output is given on `stdin`.

**Interactive problems**
For interactive problems (`validation: custom interactive`), the invocation is
the same as above, but `stdin` is a pipe that feeds team output into the
validator instead of a file.
Similarly, `stdout` is connected to a pipe that forwards to the submission's `stdin`.

**Example usage**

Suppose a problem requires as output some integer `x`, and then any two integers
that sum to `x`. Then, the output validator could first read `x` from the `.ans`
file (second argument), and compare that to the `x` given on `stdin`. Then, it
can read the remaining two integers on `stdin` and verify they sum to `x`.

## `data/bad` validation (out-of-spec)

BAPCtools allows testcases in `data/bad` to test that validators fail on
specific types of input/output that do not follow the constraints. In
particular:

- If `data/bad/<testcase>.in` is present and the corresponding `.ans` is not
  present, the input format validator is run on this `.in` and it must fail (return `43`).
- If both `data/bad/<testcase>.{in,ans}` are present, the `.in` is assumed to be
  valid, and the output format validator is run on the `.ans` and it must fail (return `43`).
