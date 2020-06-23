# Generators

Generators are provided in the `generators/` directory and may be used to
generate test cases.  If it is present, the file `generators/generators.yaml`
specifies which testcases should be generated and which commands should be run
to generate them. See [generators.yaml](generators.yaml) for an full example
configuration with comments explaining all the valid keys.

When `generators/generators.yaml` is present, _all_ test cases in
`data/{sample,secret}` must be mentioned by it. It is not allowed to generate
some testcases while not mentioning others. Testcases must be explicitly
listed as manually created to prevent this issue.

Below are an explanation of the specification and a formal [CUE specification](#cue-specification).

## Specification

The two main object types are `directory` and `generator`. The root of `generators.yaml` is a `directory` which corresponds to the `data/` directory.

**Directory objects** take the following keys:
* `type`: This must be set to `directory`.
* `testdata.yaml`: Optional yaml configuration that will be copied to `testdata.yaml` in this directory.
* `solution`: Optional invocation of a solution to be used to generate `.ans` files. Set to empty to disable generating `.ans`. (Useful for e.g. the `data/samples/` directory.) This must be an absolute path relative to the problem root.
* `visualizer`: Optional invocation of a visualizer to generate visualizations for each test case in this directory.
    This must be an absolute path relative to the problem root. Set to empty to disable.
* `random_salt`: Optional string that will be prepended to each command before computing its `{seed}`. May be used to regenerate all random cases and to prevent predictable seeds.
* `data`: The test cases / test groups contained in this directory. This may take two forms:
    * A dictionary, each key is the name of a test case/test group, and each value must be a `directory` or `generator` object.
    * A list of dictionaries as above. In this case, testcases will be prefixed with zero padded 1-based integers in the order of the list. Items in the same dictionary will get the same number.

**Generator objects** have one of the following forms:
- `null`: An empty generator means that the testcase is a manual case and must not be modified or deleted by generator tooling. The corresponding `.in` file must be present in the `data/` directory. The corresponding `.ans` may be present, but may also be generated once from a given solution. Note that this form is discouraged. Prefer specifying a path to a `.in` file as below.
- `command`: A command can take two forms:
    - A path to a `.in` file which must be relative to `generators/`. The `.in` file and corresponding files with known extensions will be copied to the specified location. If a `.ans` is not specified and a `solution` is provided, it will be used to generate the `.ans`.
    - An invocation of a generator: `<generator_name> <arguments>`. `<generator_name>` must either be a program (file/directory) in `generators/` or else a name in the top level `generators` dictionary (see below). Arguments may contain `{name}` to refer to the name of the testcase and `{seed}` or `{seed:(0-9)+}` to add a random seed. Arguments are separated by white space (space, tab, newline). Quoting white space is not supported.

- A dictionary containing `type: testcase`. In this case, `input` is a `command` as above, and the dictionary may furthermore contain the `solution`, `visualizer`, and `random_salt` keys to specialize them for this testcase only.

**Root object**
The root of the `generators.yaml` is a `directory` object with one optional additional key:

* `generators`: a dictionary mapping generator names to a list of dependencies.
    This must be used when using non-directory generators that depend on other files in the `generators/` directory. Each key of the dictionary is the name of a generator, and values must be lists of file paths relative to `generators/`.

    When this dictionary contains a name that's also a file in `generators/`, the version specified in the `generators` dictionary will have priority.

    Generators specified in the `generators` dictionary are built by coping the list of files into a new directory, and then building the resulting program as usual. The first dependency listed will be used to determine the entry point.

    Other generators are built as (file or directory) [programs](./Problem_Format#Programs).


## CUE specification.

Below is a formal [CUE](https://cuelang.org/docs/references/spec/) specification for the `generators.yaml` file with a root object `Generators`. Note that the `...` in `generator` and `directory` indicate that additional keys unknown to the spec are allowed. The `generator_reserved` and `directory_reserved` objects indicate keys that work only for `generator`/`directory` and should not be reused in other places.

```
command :: !="" & (=~"^[^{}]*(\\{(name|seed(:[0-9]+)?)\\}[^{}]*)*$")
file_config :: {
    solution?: command | null
    visualizer?: command | null
    random_salt?: string
}
generator :: command | {
    type: "testcase"
    input: command
    file_config
    directory_reserved
    ...
}
data_dict :: {
    [string]: directory | generator | null
}
directory :: {
    type: "directory"
    file_config
    "testdata.yaml"?: {
        ...
    }
    data?: data_dict | [...data_dict]
    generator_reserved
    ...
}
Generators :: {
    generators?: {
        [string]: [...string]
    }
    directory
}

generator_reserved :: {
    input?: _|_
    ...
}
directory_reserved :: {
    data?: _|_
    include?: _|_
    "testdata.yaml"?: _|_
    ...
}
```
