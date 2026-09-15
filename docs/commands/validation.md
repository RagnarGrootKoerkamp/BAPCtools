# Problem validation

## `validate`

Use `bt validate --input [<test_cases>]` to validate the `.in` files for the given test cases, or all test cases when not specified.

See `run <test_cases>` for a description of how to pass test cases.

`bt validate --answer <test_cases>` is similar to `bt validate --input` but validates `.ans` files instead of `.in` files.

`bt validate --invalid <invalid_test_cases>` checks invalid test cases in `data/invalid_*`.

`bt validate --valid-output <valid_test_cases>` checks valid test cases in `data/valid_output`.

`bt validate --generic <type>` automatically generates generic (in)valid test cases (like those in `data/valid_output` or `data/invalid_*`) and checks them.
`dir` must be one of `valid_input`, `valid_answer`, `valid_output`, or `valid_output`

`bt validate` runs all of the above.

It supports the following flags when run for a single problem:

- `[test_cases]`: a list of test cases and/or directories to validate.
See `run <test_cases>` for allowed formats.
When not set, all test cases are validated.
- `--remove`: when passed, all invalid test cases are deleted.
- `--move-to <directory>`: when passed, all invalid test cases are moved to the given directory.
- `--no-test-case-sanity-checks`: when passed, all sanity checks on the test cases are skipped.
You might want to set this in `.bapctools.yaml`.

## `constraints`

`bt constraints` has two purposes:

1. Verify that the bounds in the input/output validators match the bounds in the test cases.
1. Verify that the bounds in the problem statement match the bounds in the input/output validators.

See the [implementation notes](../advanced/implementation_notes.md#constraints-checking) for more info.

**Verify test case**

Validators that accept the `--constraints_file <path>` option are run on all test cases to check whether the bounds specified in the validator are actually reached by the test data.
A warning is raised when this is not the case.
E.g. when an `input_validator` based on [headers/validation.h]({{ repo_url }}/blob/main/bapctools/resources/headers/validation.h) does `v.read_integer("n", 1, 1000)` (on line `7`) and the maximum value of `n` over all test cases is `999`, the following warning will be raised:

```
WARNING: BOUND NOT REACHED: The value at input_validator.cpp:7 was never equal to the upper bound of 1000. Max value found: 999
```

**Verify problem statement**

The command also runs some regexes over the input validator, output validator, and LaTeX sources to look for numeric bounds.
These are then displayed next to each other to make it easy to **manually verify** that the bounds used in the statement match the bounds used in the validators.

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
- `--all`/`-a`: run all test cases and don't stop after first error
- `--no-generate`/`-G`: Do not generate test cases before running.
This usually won't be needed since checking that generated test cases are up to date is fast.
