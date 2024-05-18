package problemformat

// Use cue version 0.6 or later
// To validate generators.yaml using cue:
// > cue vet generators.yaml *.cue -d "#Generators"

import "struct"

// A command invokes a generator, like "tree --n 5".
// The regex restricts occurrences of curly-bracketed expressions
// to things like "tree --random --seed {seed:5} {name} {count}"
// - {seed} can occur at most once
// - {name} and {count} can occur any number of times
command: !="" & (=~"^([^{}]|\\{name\\}|\\{count\\})*(\\{seed(:[0-9]+)?\\})?([^{}]|\\{name\\}|\\{count\\})*$")

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
		count?: int & >= 1 & <= 100
		// The "copy" key uses a path relative to "/generators/" ending in a testcase name,
		// such as "manual/samples/3".
		copy?:                                    casepath
		["in" | "ans" | "out" | "desc" | "hint"]: string
		interaction?:                             =~"^([<>][^\\n]*\\n)+$"
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
