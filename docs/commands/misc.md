# Miscellaneous

## `all`

This is a convenience command (mostly for use in CI) that runs the following subcommands in sequence for the current problem or each problem in the current contest:

- Build the problem pdf.
- Generate test cases, and check they are generated deterministically
- Validate input
- Validate output
- Run all submissions

This supports the `--cp` and `--no-time-limit` flags which are described under the `pdf` subcommand and the `--no-test-case-sanity-checks` flag from `validate`.

## `solve_stats`

Generates solve statistics that can be used in the solution presentation.
This command uses Matplotlib to generate one PDF for every problem (shown in the top-right of the slide), one PDF for the language statistics (optionally included in `solution_footer.tex`), and one TeX file that provides the data for the `\solvestats` command.

This command uses the `/teams?public=1` API endpoint of DOMjudge, so all teams on the public scoreboard are included (including spectator/company teams).

**Flags**

- `--contest-id`: Contest ID to use when reading from the API.
Defaults to value of `contest_id` in `contest.yaml`.
- `--post-freeze`: When given, the solve stats will include submissions from after the scoreboard freeze.

## `sort`

Prints a list of all problems in the current contest (or single problem), together with their letter/ID:

```sh
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

```sh
~bapc/findmyfamily % bt tmp
/tmp/bapctools_ef27b4/findmyfamily
```

This is useful for development/debugging in combination with `cd`:

```
cd `bt tmp`
```

**Flags**

- `--clean`: deletes the entire temporary (cache) directory for the current problem/contest.
