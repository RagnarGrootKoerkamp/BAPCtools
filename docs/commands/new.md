# New Contest/Problem

## `new_contest`

This command creates a new contest.
Can be called as `bt new_contest` or `bt new_contest <contest name>`.
Settings for this contest will be asked for interactively.
The following files are copied from [skel/contest]({{ repo_url }}/tree/main/bapctools/resources/skel/contest):

- `contest.yaml` containing data for rendering the contest pdf.
- `problems.yaml` containing the list of problems and their labels.
- `languages.yaml` containing the list of languages to use.
This may be deleted to use the default instead, or changed to e.g. only allow a subset of languages.
- `logo.pdf` for the contest pdf.
- `solution_{header,footer}.tex` contains extra slides for the solutions presentation.

```sh
/tmp/tmp % bt new_contest
name: NWERC 2020
subtitle: The Northwestern European Programming Contest 2020
dirname (nwerc2020):
author (The NWERC 2020 jury):
test session? (y/N): n
year (2020):
source url: 2020.nwerc.eu
license (cc by-sa):
rights owner (if left empty, defaults to problem author):
```

## `new_problem`

Create a new problem directory and fill it with skel files.
If `problems.yaml` is present, also add the problem to it.
Information can be passed in either interactively or via command line arguments:

```sh
~nwerc2020 % bt new_problem
problem name (en): Test Problem
dirname (testproblem):
author: Ragnar Groot Koerkamp
type (pass-fail):
source (NWERC 2020):
source url (2020.nwerc.eu):
license (cc by-sa):
rights owner (if left empty, defaults to problem author):
LOG: Copying /home/philae/git/bapc/BAPCtools/skel/problem to testproblem.
```

```sh
~nwerc2020 % bt new_problem 'Test Problem 2' --author 'Ragnar Groot Koerkamp' --type interactive
LOG: Copying /home/philae/git/bapc/BAPCtools/skel/problem to testproblem2.
```

Files are usually copied from [skel/problem]({{ repo_url }}/tree/main/bapctools/resources/skel/problem), but this can be overridden as follows:

- If the `--skel <directory>` flag is specified, that directory is used instead.
- If either the current (contest) directory or the parent directory contains a `skel/problem` directory, that is used instead.
This can be used to override the default problem template on a per-contest basis.

**Flags**

- `[<problem name>]`: The name of the problem.
Will be asked interactively if not specified.
- `--author`: The author of the problem.
Will be asked interactively if not specified.
- `--type`: The problem type to use.
Must be one of `pass-fail`, `float`, `custom`, `interactive`, `multi-pass`, or `interactive multi-pass`.
- `--defaults`: Assume the defaults for fields not passed as arguments.
This skips input-prompts but fails when defaults cannot be assumed.

## `skel`

Copy the given directory from [../skel/problem]({{ repo_url }}/tree/main/bapctools/resources/skel/problem) to the current problem directory.
Directories passed must be relative to the problem root, e.g. `generators` or `output_validators/output_validator`.
The skel directory is found as with the `new_problem` command and can be overridden using `--skel`.

## `rename_problem`

Rename a problem, including its problem directory.
If `problems.yaml` is present, also rename the problem in this file.
For multilingual problmems, asks for problem names in all languages;
the default problem directory name is based on the English problem name (if present.)
Do not forget to pass a `--problem` to rename when running this from a contest directory.

**Flags**

- `[<problem name>]`: The new name of the problem.
	Will be asked interactively if not specified.
