# Latex

## `pdf`

Renders a pdf for the current problem or contest.
The pdf is written to `problem.en.pdf` or `contest.en.pdf` respectively.
If there are problem statements (and problem names in `problem.yaml`) present for other languages, creates those PDFs as well.

!!! note
    All LaTeX compilation is done in tmpfs (`/tmp/` on linux).
    The resulting pdfs will be symlinks into the temporary directory.
    See the [Implementation notes](../advanced/implementation_notes.md#building-latex-files) for more.

**Flags**

- `--all`/`-a`: When run from the contest level, this enables building pdfs for all problems in the contest as well.
- `--cp`: Instead of symlinking the final pdf, copy it into the problem/contest directory.
- `--no-time-limit`: When passed, time limits will not be shown in the problem/contest pdfs.
- `--watch`/`-w`: Continuously compile the pdf whenever a `problem.en.tex` changes. Note that this does not pick up changes to `*.yaml` configuration files.
Note that this implies `--cp`.
- `--open <program>`/`-o <program>`: Open the continuously compiled pdf (with a specified program).
- `--web`: Build a web version of the pdf.
This uses [contest-web.tex]({{ repo_url }}/tree/main/bapctools/resources/latex/contest-web.tex) instead of [contest.tex]({{ repo_url }}/tree/main/bapctools/resources/latex/contest.tex) and [problem-web.tex]({{ repo_url }}/tree/main/bapctools/resources/latex/problem-web.tex) instead of [problem.tex]({{ repo_url }}/tree/main/bapctools/resources/latex/problem.tex).
In practice, the only thing this does is to remove empty _this is not a blank page_ pages and make the pdf single sides.
- `-1`: Run the LaTeX compiler only once.

## `solutions`
{{ repo_url }}
Renders a pdf with solutions for the current problem or contest.
The pdf is written to `solution.en.pdf` or `solutions.en.pdf` respectively, and is a symlink to the generated pdf which is in a temporary directory.
See the [Implementation notes](../advanced/implementation_notes.md#building-latex-files) for more.

**Flags**

- `--cp`: Instead of symlinking the final pdf, copy it into the contest directory.
- `--order`: The order of the problems, e.g. `BDCA`.
Can be used to order problems from easy to difficult.
When labels have multiple letters, `B1,A1,A2,B2` is also allowed.
- `--order-from-ccs`: Order the problems by increasing difficulty, extracted from the api, e.g.: https://www.domjudge.org/demoweb.
Defaults to value of `api` in contest.yaml.
- `--contest-id`: Contest ID to use when reading from the API.
Only useful with `--order-from-ccs`.
Defaults to value of `contest_id` in `contest.yaml`.
- `--watch`/`-w`: Continuously compile the pdf whenever a `solution.en.tex` changes.
Note that this does not pick up changes to `*.yaml` configuration files.
Note that this implies `--cp`.
- `--open <program>`/`-o <program>`: Open the continuously compiled pdf (with a specified program).
- `--web`: Build a web version of the pdf.
This uses [contest-web.tex]({{ repo_url }}/tree/main/bapctools/resources/latex/contest-web.tex) instead of [contest.tex]({{ repo_url }}/tree/main/bapctools/resources/latex/contest.tex) and [solutions-web.tex]({{ repo_url }}/tree/main/bapctools/resources/latex/solutions-web.tex) instead of [solutions.tex]({{ repo_url }}/tree/main/bapctools/resources/latex/solutions.tex).
In practice, the only thing this does is to remove empty _this is not a blank page_ pages.
- `-1`: Run the LaTeX compiler only once.

## `problem_slides`

Renders a pdf with problem slides for the current problem or contest.
The pdf is written to `problem-slide.en.pdf` or `problem-slides.en.pdf` respectively, and is a symlink to the generated pdf which is in a temporary directory.
See the [Implementation notes](../advanced/implementation_notes.md#building-latex-files) for more.

**Flags**

- `--cp`: Instead of symlinking the final pdf, copy it into the contest directory.
- `--watch`/`-w`: Continuously compile the pdf whenever a `problem-slide.en.tex` changes.
Note that this does not pick up changes to `*.yaml` configuration files.
Note that this implies `--cp`.
- `--open <program>`/`-o <program>`: Open the continuously compiled pdf (with a specified program).
- `-1`: Run the LaTeX compiler only once.
