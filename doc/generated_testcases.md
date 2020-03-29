# Spec for `generators/gen.yaml`

## Example config
The following `generators/gen.yaml` would specify which files to generate. It should be self explanatory.
```yaml
config:
  extensions: # The following extensions will be created for each .in that's generated
    ans: ../solutions/accepted/sol.py
    png: asy.py ../visualizers/vis.asy -f png -o - # Note that directly calling a shell executable is not allowed

# Following test cases will be created in the `sample` directory.
sample:
  config:
    extensions:
      ans: # empty to disable generating .ans files here
  1.in:    stdout.py 1  # prints `1` to stdout, which is piped to 1.in

secret:
  manual.in:      # optionally list manual case with empty arguments
# manual-2.in     # not listed but still fine.
  3.in: stdout.py 3
  4.in: cpp.cpp 4 # Similarly to validators, a generator can be a c++/java/.. file or directory
  10.in:
    - stdout.py 5
    - double.py # generator that doubles the number. Reads stdout of the previous command from stdin.

  testgroup:  # creates a subdirectory because it doesn't end in `.in`.
    testdata.yaml: # Contents are copied to testgroup/testdata.yaml
      on_reject: break
      accept_score: 25
      range: 0 25
      grader_flags: min
    a.in: stdout.py a
    b.in: stdout.py b

  other_testgroup:
    config:
      extensions:
        ans: generated # Make sure the .ans generated below is preserved.
    test.in: in_ans_generator.py $PATH # $PATH=test.in. writes .in to stdout and .ans to test.ans.

  # $SEED is computed as the last 31 bits of the sha512 hash of the command:
  # SEED = int(hashlib.sha512(command.encode('utf-8')).hexdigest(), 16)%(2**31)
  random-1.in:    stdout.py $SEED
  random-1a.in:   stdout.py $SEED   # same seed, so same test data is generated
  random-2.in:    stdout.py $SEED2  # different $SEED, because of extra `2`
# random-3.in:    stdout.py 1$SEED2 # doesn't substitute $SEED because it's not a prefix

  string.in: stdout.py "a b" # gives a single string of length 3 as argument

  random_graphs: write_random_graphs.py # rule that writes multiple testcases in the random_graphs directory

  test.in: # writes tree.txt and path.txt files. Then reads them and prints the final testcase to stdout
    - tree.py 10 tree.txt
    - path.py 20 path.txt
    - combine.py tree.txt path.txt

# Forbidden because of /
#secret/5.in:      stdout.py 5
```

## TL;DR
For a each rule `test.in` ending in `.in`, execute the command(s) as:
```
command1 | ... | commandn > test.in
```
These commands may write and read local files and pipes do not _have_ to be
used. For extensions that are marked as `generated` in `config: extensions:`,
`testcase.ext` will be preserved. Any other generated files are ignored/deleted.

For any other rule, create a directory and execute the command(s) as:
```
command1
...
commandn
```
No `stdin` is provided and any `stdout` is ignored in this case.

For each transformation to `ext` as specified in the `extensions` config, execute
```
command1 < test.in | ... | commandn > test.ext
```
Files created by these commands will not be copied to `data/`.

**TODO**: Do we also need to support commands that write the file directly? The
current proposal is to keep this consistent with simple generators.

## Formal Spec
Test cases can be generated from `generators/gen.yaml` containing a dictionary at the top level.
`key`s indicates the path of the test case, and the `rules`s contain the generators to run.

### Keys
Keys must confirm to the regex for [problem-archive file names](https://problemarchive.com/wiki/index.php/Problem_Format#General_Requirements)
```
[a-zA-Z0-9][a-zA-Z0-9_.-]*[a-zA-Z0-9]
```
Keys indicate the path (file or directory) of the test data. The top level keys
are relative to the `data/` directory.
There are two types of keys:
- Keys ending in `.in` (e.g. `testcase.in`) must contain a string or list of
  strings. These denote how that specific test case is
  generated. Their generator commands must write to `stdout`.
- All other keys, like `testgroup` create a subdirectory. This may contain
  either:
    - a dictionary of nested keys
    - or a (list of) string(s), which is a list of commands executed to create
      the data in this directory.

The keys `config` and `testdata.yaml` are reserved. See below.

### Values
The value of a key must be one of:
- a dictionary: the keys in this dictionary are treated as above
- empty (`None`): nothing will be done. This can be used to indicate manually created test data files.
- a single string
- a list of strings

The last two cases are called _rules_. Each _rule_ is a list of commands that
will be executed to create the test case(s) for the current key.

Each string indicates a command that will be executed.
The string may contain shell escaped white space and will be split using
[shlex.split](https://docs.python.org/3.7/library/shlex.html#shlex.split). The
first token must be the name of the generator that's used. Similar to output
validators, this must the be name of a file or directory in `generators/`. The
remaining tokens are passed as command line arguments to the generator.

When the key is a single test case name (`testcase.in`), the commands are
executed as
```
command1 | ... | commandn > test.in
```
The last command must write the test case to `stdout`. Files may be written, but
only files matching the current test case name, followed by an extension that is
marked as `generated` in `config: extensions:` will be preserved. Other files
will be deleted.

When the key does not end in `.in`, a new directory is created instead, and the
commands are executed one by one:
```
command1
...
commandn
```
In this case, no `stdin` or `stdout` is provided and the command may write any
file and read any file that was created by earlier commands.

**Note:** In this last case, it is not allowed to add manual files/test cases to this
directory. A `clean` command is allowed to delete all files in this directory.

**Special tokens**
After tokenizing the `value` as a shell command line, there are two tokens that have a special meaning:
- `$SEED`: Any argument that has `$SEED` **as a prefix** will be replaced by an integer: the hash of the entire `value` in its string representation. It's value is the last `31` bits of the `sha512` hash of the value: `int(hashlib.sha512(value.encode('utf-8')).hexdigest(), 16) % (2**31)`
  To call the same generator twice with the same command line arguments, but a different random seed, you can use `$SEED1`, `$SEED2`, and so on.
- `$PATH`: Any argument that exactly matches `$PATH` will be replaced by the
  current target.
    - For simple `testcase.in: gen.py $PATH` rules, this will be `testcase.in`.
    - For directory rules `testgroup: gen_files.py $PATH` this will be `testgroup`.
    - For extensions, this will be the name of the file that's being generated.
      E.g. in `extensions: ans: sol.py $PATH` it will be `testcase.ans`.

Other than reading `$SEED`, Generators most be deterministic and idempotent: multiple runs of the same generator with the same arguments must produce the exact same output.
Running the same (list of) generators twice should not generate different output. In particular, rerunning a generator inside `data/` (as opposed to a clean directory in `/tmp/`) should not change anything.

### Config
Some additional configuration can be specified via the `config` key. It may
contain the `extensions` key, containing a dictionary from file extensions to
rules.
For each `.in` file that is generated, the commands for each extension in this
map will be executed to create the corresponding files (e.g. `.ans` and `.png`).
If specified, the `.ans` will be generated first, followed by all other
extensions in unspecified order.

Each extension may also have the special value `generated`. This means files of
this extension will be written by the generators directly, and are preserved
instead of deleted.

Consider:
```
config:
  extensions:
    ans: ../solutions/accepted/sol.py
    png: asy.py ../visualizers/vis.asy -f png -o -
    hint: generated
```
In this case, for each `.in` that's generated two commands are run:
- `sol.py < test.in > test.ans`
- `asy.py ../visualizers/vis.asy -f png -o - < test.in > test.png`
- `testcase.hint` will be generated by the generators directly.

In case the value is a list of commands, they will be piped into each other,
like for generating `.in` files.

**TODO:** Are there cases where this is not sufficient and the transformations
would be easier if they wrote to the file directly instead?

Config may be present in any dictionary at any level. In this case it overrides (specializes) the more global config(s).
Add an empty key to reset a previously set value.

### testdata.yaml

The `testdata.yaml` key may contain arbitrary YAML. This will be written to the
`testdata.yaml` file in the directory pointed to by the current key.

## Tooling

Using the `gen.yaml` file, tooling can do the following things:
- `generate`: Generate all testdata as specified above. Output of unchanged rules may be cached.
- `clean`: Delete all generated data:
   - `.in` files that we generated
   - Corresponding `.ans`/`.png`/... extensions that are specified as
     `extensions`.
   - Completely clean all generated directories for non-`.in` generators.
- Before running a submission, the tooling could verify that all test data is up to date. (Useful when cloning a git repository and the user is not aware some test data needs to be generated first.)
- Tooling may want to use extra `config:` settings to specify which files should be cleaned (`.ans` as well? All files with the same basename?).
