# Personal Configuration

BAPCtools uses a different location for its configuration based on the system you are using:
Configuration files for BAPCtools are placed here:

- Unix-ish with `$XDG_CONFIG_HOME`: `$XDG_CONFIG_HOME/bapctools/`
- Unix-ish: `<home>/.config/bapctools`
- macOS: `<home>/Library/Application Support/"`
- Windows: `%AppData%/bapctools/`

## Flags

For some command-line flags, it is convenient if they are always set to the same value, which differs per user (e.g., `--username` or `--password` for commands that access a CCS like DOMjudge) or per contest (e.g., which statement languages are used).
For this, you can create a configuration YAML file containing key-value pairs in one of the following locations, from low to high priority:

- `<bapctools>/config.yaml`
- `<contest directory>/.bapctools.yaml`
- `<contest directory>/<problem directors>/.bapctools.yaml`

The keys in this config file can be any option that can be passed on the command-line.
Note that the keys should be written out in full (e.g., `username: jury` rather than `u: jury`) and any hyphens should be replaced with an underscore (e.g., `no_bar: True` rather than `no-bar: True`).

### Additional Flags

some setings are only available via this config file:

- `local_time_multiplier`: float, used to adjust hardcoded time limits intended for different hardware.
This might be useful for the CI or if your hardware is much faster or much slower than the contest hardware.
- `ignore_warning`: list of Strings.
If a warning is printed which matches one of the entries it is not considered for the exit code evalation.
This might be useful for the CI if you intend to ignore a specific warning.


## Languages

BAPCtools ships a list of preconfigured languages that it can use to build and run programs.
However, it might be necessary to adjust this for your system or for a specific contest, e.g., to match the settings on the CCS.
For this, you can create a configuration YAML file in one of the following locations, from low to high priority:

- `<bapctools>/languages.yaml`
- `<contest directory>/languages.yaml`

### Language configuration for Kattis Problem Format
The language configuration consists of a dictionary of languages.
The keys in the dictionary are lower-case alphanumeric identifiers (must match the regular expression `[a-z][a-z0-9]*`).
Each language is in turn a dictionary which may contain the following six keys:

- `name`: String, name of the language.
- `priority`: Integer indicating the tie-breaker priority of this language for language detection.
See [language detection](#language-detection) below.
All languages must have distinct priorities.
- `files`: String, space-separated glob patterns indicating what files are considered source files.
- `shebang_files`: Optional, string, space-separated glob patterns, for language detection only.
Must be given together with "shebang".
See semantics under [language detection](#language-detection) below.
- `shebang`: Optional, string, regular expression, for language detection only.  Must be given together with "shebang_files".  See semantics under "language detection" below.
- `compile`: Optional, string, command to compile or syntax-check the source code.
- `run`: String, command to run a program.

### Language detection
Language detection proceeds as follows:

1. For each language, a file included in the program is considered to be a source file if its name matches the `files` glob for the language.
Once a program's language has been settled, this is the full set of source files for the program – `shebang_files` and `shebang` (see below) play no further part.
1. For the purposes of auto-detection only, a source file additionally counts as *evidence* for a language if either it doesn't match the language's `shebang_files` glob, or its first line matches `shebang`.
This lets a language claim only some of the files matching its `files` glob as its own during detection, e.g. to distinguish Python 2 from Python 3 based on a `#!...python2` shebang while still treating shebang-less helper files as belonging to whichever language wins.
1. For each language, count how many files in the program count as evidence for that language (per step 2).
1. The language of the program is the one under which the program has the maximum number of matching files.
In case of ties, the language that has the highest priority takes precedence.

### Entry point type
A language can have three different entry point types, reflecting how a program in the language is started:

- `binary`: the compile command produces an executable file
- `mainfile`: name of source code file to pass to interpreter/runtime environment as entry point to the program.
- `mainclass`: similar to mainfile, but at a higher level than a file.
Typical (only?) examples are Java and Java-based languages such as Scala.

The entry point type of a language is implicitly specified by using one of the four meta-variables `{binary}`, `{mainfile}`, `{mainclass}`, `{Mainclass}` defined below.
A language specification *must* use exactly one of these four metavariables.

### Metavariables
The following metavariables are available for use in the `compile` and `run` entries of a language.

- `{path}`: path where the source files are located
- `{files}`: list of all source files
- `{binary}`: arbitrary file name that can be defined by the implementation.
- `{mainfile}`:
    - if the program consists of a single source file, {mainfile} equals the name of that source file.
    - if the program contains a source file matching the glob `[mM][aA][iI][nN].*`, `{mainfile}` equals the name of that file (in case of multiple such files, behaviour is undefined).
    - otherwise, `{mainfile}` equals the lexicographically smallest source file name
- `{mainclass}`: equals `{mainfile}` without filename extension.
- `{Mainclass}`: equals `{mainclass}`, but first letter capitalized.
- `{memlim}`: memory limit

### Example

```yaml
python3:
    name: 'Python 3 (w/PyPy3)'
    priority: 850
    files: '*.py *.py3'
    compile: 'pypy3 -m py_compile {files}'
    run: 'pypy3 "{mainfile}"'

python2:
    name: 'Python 2 (w/PyPy)'
    priority: 860
    files: '*.py *.py2'
    shebang_files: '*.py'
    shebang: '^#!.*python2\b'
    compile: 'pypy2 -m py_compile {files}'
    run: 'pypy2 "{mainfile}"'
```
