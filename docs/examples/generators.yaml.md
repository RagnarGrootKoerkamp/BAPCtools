# `generators.yaml`

This file is located under `problem_name/generators/generators.yaml`

```yaml
# The solution is used to generate a .ans for each generated .in which doesn't
# yet have a corresponding .ans. If there are generators that don't write a .ans
# file themselves, a solution must be specified.
# This should read the input from stdin and write to stdout.
#
# This must be the absolute path to the solution, starting in the problem root.
solution: /submissions/accepted/sol.py

# Optionally, a salt for generating the {seed} variables. Will be prepended to
# the command being run.
random_salt: abcd

# The top level may contain a test_group.yaml that will be written to data/ as specified.
test_group.yaml:
  output_validator_args: []

# We support three types of generators:
# - Standalone files, like generators/a.cpp, generators/b.py, ..., which will
#   be compiled if required and run the same way as submissions.
# - Directories, like generators/gen containing files:
#   - generators/gen/tree.cpp
#   - generators/gen/lib.h
#   This will be compiled and run the same way as directory validators. Build
#   and run scripts may be used, as explained in ../spec/problem_package_format#programs.
# - 'implicit' generators whose dependencies are specified in the `generators:`
#   key below. The dependencies may refer to any files relative to generators/.
#   The generator will be built and run as if they formed a separate directory.
#   The first item in the list will be used as entry point.
#   E.g. the first example below would be equivalent to the two files
#   - generators/tree/tree.py
#   - generators/tree/lib.py
#
# For each generator name specified in a command to generate a .in
# file, we first check if this name is a key in the `generators:` dictionary below. If so,
# the corresponding generator is used. If not, we will use the generator with that
# file/directory name in the `generators/` directory directly.
generators:
  # A generator that depends on two files, a.py and b.py, directly in the generators directory.
  example:
    - example_a.py
    - example_b.py

# The data: keyword contains the list of test cases and test data groups.
# Note that this is different from the data/ directory, which is where the keys
# of this top-level data: dictionary will be written.
data:
  # Introduce the `sample` directory.
  sample:
    data:
      # list are automatically numbered => this becomes 01.in
      - "":
          in: <valid input>
          ans: <valid answer>
          # optional overwrites that are used for the statement / downloads
          # You can use {link: xxx} to reuse xxx
          in.statement: <statement input>
          ans.statement: <statement answer>
          in.download: <download input>
          ans.download: <download answer>
          # test-case.yaml
          yaml:
            description: <description>
            hint: <hint>
          # lists of regexes that the test case files must match
          match:
            in: []
            ans: []
      # this now becomes 02.in
      - "":
          # The copy key indicates a manual test case that will be copied
          # from the given directory into the target test case. The given directory
          # must not start with a /, not include an extension and will be relative to generators/.
          copy: manual_cases/1
          # if no ans: is given it will be generated from a solution
      # run a generator => 03.in
      - "": generator.py {seed}

  secret:
    include:
      # You can include other test groups by their yaml name
      - "sample"
      # This will include "01", "02", and "03" from sample
    data:
      # The regex \{seed(:[0-9]+)?\} (e.g. {seed} or {seed:1}) anywhere in the argument
      # string will be replaced by an integer hash of the entire command in [0, 2^31).
      - random: generator.py {seed}
      - random:
          generate: generator.py {seed} {count}
          # generate ten test cases at once, value for {count} will be [1,2,...,10]
          # the value of seed will change for each of the 10 test cases
          count: 10
          # more advanced syntax to define what values replace {count}
          # count: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
          # count: 1..=10
      - yaml_example:
          # This uses YAML multiline string syntax to define the input
          in: |
            first line
            second line
            third line
      - group:
        data:
          "a": generator.py {seed:1}
          "b": generator.py {seed:2}
          "c": generator.py {seed:3}

 invalid_input:
    # Add invalid test cases to ensure that input_validators correctly rejects them.
    data:
      invalid_test_case_input:
        in: <invalid input>

  invalid_answer:
    # Add valid test cases with invalid answers to ensure that the answer_validators correctly rejects them.
    # (The output validator is also called with these)
    data:
      invalid_test_case_answer:
        in: <valid input>
        ans: <invalid answer>

  invalid_output:
    # Add valid test cases with answer and invalid team output to ensure that the output_validator correctly rejects them.
    data:
      invalid_test_case_output:
        in: <valid input>
        ans: <valid answer>
        out: <invalid output>

  valid_output:
    # Add valid test cases with answer and team output to ensure that the output_validator correctly accepts them.
    data:
      valid_test_case_output:
        in: <valid input>
        ans: <valid answer>
        out: <valid output>
```
