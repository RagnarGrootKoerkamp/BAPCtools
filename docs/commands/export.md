
# Exporting

## `samplezip`

Create `contest/samples.zip` containing the sample `.in` and `.ans` files for all samples in the current problem or contest.
Samples are always numbered starting at `1`:

```sh
~bapc % bt samplezip
Wrote zip to samples.zip
~bapc % unzip -l samples.zip
Archive:  samples.zip
  Length      Date    Time    Name
-------------------------------------
       18  2020-05-06 20:36   A/1.in
        3  2020-05-06 20:36   A/1.ans
       44  2020-05-06 20:36   A/2.in
        4  2020-05-06 20:36   A/2.ans
        2  2020-05-06 20:36   B/1.in
        8  2020-05-06 20:36   B/1.ans
...
```

## `zip`

This creates a problem or contest zip that can be directly imported into DOMjudge.
Specify the `--kattis` flag for a zip compatible with `problemtools`.
Differences are explained below.

When run for a problem:

- Build the problem pdf.
- Verify problem input and output, with constraint checking.
- Write a zip containing all problem data to `contest/<problemlabel>.zip`, e.g. `contest/A.zip`.

When run for a contest:

- First build a zip for each problem, as above.
- Build the contest pdf.
- Build the contest solution slides.
- Write the contest pdf and all problem zips to a single zip: `contest/<contest>.zip`.

**Flags**

- `--skip`: Do not rebuild problem zips when building a contest zip.
- `--force`/`-f`: Skip validating input and output.
This is useful to speed up regenerating the zip with only minimal changes.
- `--no-generate`/`-G`: Skip generation of test cases.
This usually won't be needed since checking that generated test cases are up to date is fast.
- `--no-solutions`: Do not build solution slides for the contest zip.
- `--kattis`: Differences for Kattis export are:
    - Problems zips are written to `<shortname>.zip` instead of `<problemlabel>.zip`.
    - Kattis doesn't use a contest pdf, solution slides, and `contest/samples.zip`.
    - The contest level zip is written to `contest/<contest>-kattis.zip`
    - Kattis needs the `input_validators` directory, while DOMjudge doesn't use this.
    - Kattis problem zips get an additional top level directory named after the problem shortname.
    - _Statements_: Kattis’s problemtools builds statement HTML (and PDF) using `problem2html` (and `problem2pdf`) rather than `bt pdf`.
    Problem authors should check the resulting statements after exporting to Kattis; pay attention to:
        - The command `bt zip --kattis` exports `{statement,solution}/*` but not its subdirectories, so make sure illustrations and `\input`-ed tex sources are included.
        - Proper images scaling in the HTML output requires explict widths, such as `\includegraphics[width=.5\textwidth]{foo.png}`.

## `export`

This command uploads the `contest.yaml`, `problems.yaml`, and problem zips to DOMjudge.
Make sure to run the [`bt zip`](#zip) command before exporting, this does not happen automatically.

When run for a single problem, `contest.yaml` and `problems.yaml` are uploaded for the entire contest, but only the zip for the selected problem is uploaded.
