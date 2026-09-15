# Problem Development

## `run`

The `run` command is used to run some or all submissions against some or all test cases.
The syntax is:

```sh
bt run [<submissions and/or test cases>]
```

This first makes sure all generated test cases are up to date and then runs the given submissions (or all submissions by default) against the given test cases (or all test cases by default).

By default, this prints one summary line per submission containing the slowest test case.
If the submission failed, it also prints the test cases for which it failed.
Use `bt run -v` to show results for all test cases.

**Flags**

- `[<submissions and/or test cases>]`: Submissions and test cases may be freely mixed.
The arguments containing `data/` or having `.in` or `.ans` as extension will be treated as test cases.
All other arguments are interpreted as submissions.
This argument is only allowed when running directly from a problem directory, and does not work with `--problem` and `--contest`.

    Test cases and submissions should be passed as a relative or absolute path to the test case/submission.

    When submissions or test cases is not specified, they default to all submissions in `submissions/` and all test cases under `data/{sample,secret}` respectively.

    **Submission** paths can take a few forms:

    - The path of the single file: `submissions/accepted/submission.py`
    - The path of the submission directory (when it contains multiple files): `submissions/accepted/directory_submission/`
    - One of the directories inside `submissions/`: `submissions/time_limit_exceeded`.
    This will add all submissions in the given directory.
    - Any file/directory outside `submission` is also allowed.
    Directories will be interpreted as a single multi-file submission.

    Duplicate submissions will deduplicated.

    **Test cases** may be referred to in a few ways:

    - The path of the `.in` file: `data/secret/1.in`
    - The path of the `.ans` file: `data/secret/1.ans` (any other extension also works, even if the file doesn't exist)
    - The base name of the test case: `data/secret/1`
    - A directory: `data/secret`.
    In this case, all `.in` files that are (nested) in this directory will be used.

    Test cases must always be inside the `data` directory.
    Anything outside `data/` will raise an error.

    Duplicate test cases will deduplicated.
    Hence, you may pass `data/secret/*` and `1.in` and `1.ans` will not trigger the test case twice.

- `--samples`: Run the given submissions against the sample data only.
Not allowed in combination with passing in test cases directly.
- `--no-generate`/`-G`: Do not generate test cases before running the submissions.
This usually won't be needed since checking that generated test cases are up to date is fast.
- `--time-limit <second>`/`-t <second>`: The time limit to use for the submission.
- `--timeout <second>`: The timeout to use for the submission.
- `--table`: Print a table of which test cases were solved by which submissions.
May be used to deduplicate test cases that fail the same submissions.
- `--overview`/`-o`: Print a live overview of the received verdicts for all submissions and test cases.
If combined with `--no-bar` only the final table is printed.
- `--no-test-case-sanity-checks`: when passed, all sanity checks on the test cases are skipped.
You might want to set this in `.bapctools.yaml`.
- `--sanitizer`: when passed, run submissions with additional sanitizer flags (currently only C++).
Note that this removes all memory limits for submissions.
- `--visualizer`: when passed, run the output visualizer.

## `test`

`bt test` only works for a single problem, and must be called as

```
bt test <submission> [<test_cases>].
```

It runs the given submission against the specified test cases (or all test cases if not set) and prints the submission `stdout` and `stderr` to the terminal.
Additionally, time limits and timeouts will be reported.
For interactive problems, the interaction is shown.

This is useful for running submissions without having to compile them manually.

**Flags**

- `<submission>`: The path to the submission to run.
See `run <submissions>` for more.
- `--interactive`/`-i`: Use terminal input as test data.
`stdin` is forwarded directly to the submission.
This rebuilds and reruns the submission until either the end of the input (`control-D`) or till BAPCtools is terminated (`control-C`).

  It is also possible to pipe in test cases using e.g.

  ```sh
  bt test submissions/accepted/author.py --interactive < data/samples/1.in
  ```

  or

  ```sh
  bt test submissions/accepted/author.py -i <<< "10 20"
  ```

  in this case, the submission is only run once instead of repeatedly.

- `[<test_cases>]`: The test cases to run the submission on.
See `run <test_cases>` for more.
Can not be used together with `--samples`.
- `--samples`: Run the submission on the samples only.
Can not be used together with explicitly listed test cases.
- `--timeout <second>`/`-t <second>`: The timeout to use for the submission.

## `time_limit`

The `time_limit` command is used determine a time limit based on the `time_multipliers`: `ac_to_time_limit` and `time_limit_to_tle`.
The syntax is:

```sh
bt time_limit [<submissions and/or test cases>]
```

**Flags**
- `--write`/`-w`: write the determined time limit to `problem.yaml`
- `--all`/`-a`: run all submissions not only AC and TLE submissions.
- `<submissions>`: The path to the submission to use to determine the time limit.
See `run <submissions>` for more.
- `<test_cases>`: The path to the test cases to use determine the time limit.
See `run <test_cases>` for more.

## `generate`

Use the `generate` command to generate the test cases specified in `generators/generators.yaml`.
The syntax of this file is described in [generators.md](../generators.md) and [generators.yaml](../examples/generators.yaml.md) is an example.

This command tries to be smart about not regenerating test cases that are up to date.
When the generator and its invocation haven't changed, nothing will be done.

Any files in `data/` that are not tracked in `generators.yaml` will be removed.

Pass a list of test cases or directories to only generate a subset of data.
See [run](#run) for possible ways to pass in test cases.

**Flags**

- `--check-deterministic`: Check that the .in files are generated deterministically for all test cases, skipping the up-to-date check.
- `--add [<test_cases>, <directories>]`: Add the test cases (inside the directories) as `copy` entries in the `generator.yaml`
- `--clean`: Delete all cached files.
- `--reorder`: Runs all submissions that should fail and reorders the test cases in the given directories by difficulty.
- `--jobs <number>`/`-j <number>`: The number of parallel jobs to use when generating test cases.
Defaults to half the number of cores.
Set to `0` to disable parallelization.
- `--timeout <seconds>`/`-t <seconds>`: Override the default timeout for generators and visualizers (`30s`) and submissions (`1.5*time_limit+1`).
- `--no-validators`: Ignore the results of input and output validators.
  (They are still run.)
- `--no-solution`: Skip generating .ans or .interaction files with the solution.
- `--no-visualizer`: Skip generating graphics with the visualiser.
- `--no-test-case-sanity-checks`: when passed, all sanity checks on the test cases are skipped.
You might want to set this in `.bapctools.yaml`.

## `stats`

`bt stats` prints a table of statistics for the current problem or the problems in the current contest.
This table contains:

- The problem label and shortname.
- Whether `problem.yaml` is found.
- Whether `statement/problem.en.tex` and `solution/solution.en.tex` are found.
- Whether the problem has any `input_validators` and `output_validators`.
- The number of `sample` and `secret` test cases.
- The number of `accepted`, `wrong_answer`, and `time_limit_exceeded` solutions.
- The number of C(++), Python 3, Java, and Kotlin solutions.
- An optional comment, as specified by the `comment:` field in `problem.yaml`.
- When `verified:` is set to `true` in `problem.yaml`, the comment will be shown in green.

This may look like:

```
problem               time yaml tex sol   val: I A O    sample secret bad    AC  WA TLE subs   cpp py java kt   comment
A appealtotheaudience  1.0    Y   Y   N        Y Y           2     30   0     4   4   2   10     2  1    1  0
```

`bt stats --all` additionally prints statistics about submissions, test cases, and git usage.

## `fuzz`

Use the `fuzz` command to test all accepted submissions against random test data.
Test data is generated by randomizing the `{seed}` in `generators.yaml` rules which depend on it.

When a solution fails on a generated test case, a generator invocation for the test is stored in `generators.yaml` corresponding to `data/fuzz/<id>.in`.

**Flags**

- `[<test_cases>]`: The generator invocations to use for generating random test data.
Accepts directories (`data/secret`), test case names (`data/secret/1`), or test case files (`data/secret/1.in`).
- `--time <seconds>`/`-t <seconds>`: For how long to run the fuzzer.
- `--timeout <seconds>`: Override the default timeout for generators (`30s`).
