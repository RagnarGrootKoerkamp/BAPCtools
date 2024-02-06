package problemformat

// cue version 0.6
// To validate generators.yaml using cue:
// > cue vet generators.yaml *.cue -d "#Generators"

import "struct"

// A command invokes a generator, like "tree --n 5".
// The regex restricts occurrences of curly-bracked expressions 
// to things like "tree --random --seed {seed:5}"
command: !="" & (=~"^[^{}]*(\\{seed(:[0-9]+)?\\}[^{}]*)*$")

// Names for generators, testgroups, and testcases are alphanumerical with underscores
// and hyphens; such as "huge", "make_tree", "3", or "connected_graph-01".
let basename = "([A-Za-z0-9][A-Za-z0-9_-]*[A-Za-z0-9]|[A-Za-z0-9])"
name: =~"^\(basename)$"

// Filenames are somewhat like names, but can also contain '.' 
// and have length at least 2, such as "good-solution_02.py"
// but not "huge_" or "a".
let filename = "[A-Za-z0-9][A-Za-z0-9_.-]*[A-Za-z0-9]"

filepath: =~"^/?\(filename)(/\(filename))*$"
casepath: =~"^\(filename)(/\(basename))*$"

#config: {
	"testdata.yaml"?: #testdata_settings
	// Path to solution starts with slash, such as "/submissions/accepted/foo.py"
	solution?: filepath & =~"^/"
	// Path to visualiser can be omitted
	visualizer?:  command & =~"^/" | null
	random_salt?: string
}

#testcase:
	command |
	{
		generate?: command
		// The "copy" key uses a path relative to "/generators/" ending in a testcase name,
		// such as "manual/samples/3".
		copy?:                            casepath
		["in" | "ans" | "out" | "desc" | "hint"]: string
		interaction?:                     =~"^([<>][^\\n]*\\n)+$"
		#config
	}

#data_dict: {[name]: #testgroup | #testcase}
#data_list: {[name | ""]: #testgroup | #testcase} & struct.MinFields(1) & struct.MaxFields(1)

#testgroup: {
	data?: #data_dict | [...#data_list]
	include?: [...name]
	#config
}

#Generators: {
	// Generators are named like files or testcases, like "tree.py" or "a".
	// Each consists of a list of paths relative to "/generators/",
	// such as "tree_generator/tree.h".
	generators?: [name]: [...(filepath & !~"^/")]
	data: close({
		sample!:          #testgroup
		secret!:          #testgroup
		invalid_inputs?:  #testgroup
		invalid_answers?: #testgroup
		invalid_outputs?: #testgroup
	})
	#config

	... // Do allow unknown_key at top level for tooling
}
