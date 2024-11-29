package problemformat

// Use cue version 0.6 or later
// To validate generators.yaml using cue:
// > cue vet generators.yaml *.cue -d "#Generators"

import "struct"
import "strings"

// Directory names, as well as names of testcases and generators are
// alphanumerical with internal underscores and hyphens; such as
// "huge", "make_tree", "3", "a", or "connected_graph-01";
// but not "huge_" or "-2" or "bapc.24" or "".
let dirname = "[A-Za-z0-9]([A-Za-z0-9_-]{0,253}[A-Za-z0-9])?"
name: =~"^\(dirname)$"

// Directory paths are separated by / and do not start with a slash
dirpath: =~"^(\(dirname)/)*\(dirname)$"

// Filenames are names, but have length at least 2 and can also
// contain '.' such as "good-solution_02.py" or "1.in"
let filename = "[A-Za-z0-9][A-Za-z0-9_.-]{0,253}[A-Za-z0-9]"
filepath: =~"^/?(\(dirname)/)*\(filename)$"

// Paths can both refer to objects like the testgroup "data/secret/huge" or
// a program file like "/submissions/accepted/x.cpp"

path: dirpath | filepath

// A command invokes a generator, like "tree --n 5".
// The regex restricts occurrences of curly-bracketed expressions
// to things like "tree --random --seed {seed:5} {name} {count}"
// - {seed} can occur at most once
// - {name} and {count} can occur any number of times
command_args: =~ "([^{}]|\\{(name|count|seed(:[0-9]+)?)\\})*"
command:      C={
	!~ "\\{seed.*\\{seed" // don't use seed twice
	_parts: strings.Fields(C)
	_parts: [path, ...command_args]
}

#config: {
	"testdata.yaml"?: #testdata_settings
	// Path to solution starts with slash, such as "/submissions/accepted/foo.py"
	solution?: filepath & =~"^/"
	// Visualiser can be omitted to disable visualisation, may not use {count}
	visualizer?:  command & =~"^/" & !~"\\{count" | null
	random_salt?: string
}

#testcase:
	command & !~"^/" |
	{
		generate?: command & !~"^/"
		count?:    int & >=1 & <=100
		// The "copy" key uses a path relative to "/generators/" ending in a testcase name,
		// such as "manual/samples/3".
		copy?:                                    dirpath
		["in" | "ans" | "out" | "desc" | "hint"]: string
		interaction?:                             =~"^([<>][^\\n]*\\n)+$"
		#config
	}

#data_dict: {[name]: #testgroup | #testcase}
#data_list: {[name | ""]: #testgroup | #testcase} & struct.MinFields(1) & struct.MaxFields(1)

#testgroup: {
	data?: #data_dict | [...#data_list]
	include?: [...dirpath]
	#config
}

#Generators: {
	// Generators are named like files or testcases, like "tree.py" or "a".
	// Each consists of a nonempty list of paths relative to "/generators/",
	// such as "[tree_generator/tree.py, lib.py]".
	generators?: [name]: [...(path & !~"^/")] & [_, ...]
	data: close({
		sample!:          #testgroup
		secret!:          #testgroup
		invalid_inputs?:  #testgroup
		invalid_answers?: #testgroup
		invalid_outputs?: #testgroup
	})
	#config
	version: =~"^[0-9]{4}-[0-9]{2}$" | *"2024-12"

	... // Do allow unknown_key at top level for tooling
}
