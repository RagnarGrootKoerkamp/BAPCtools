package problemformat

// Use cue version 0.11 or later
// To validate generators.yaml using cue:
// > cue vet generators.yaml *.cue -d "#Generators"

import "struct"

import "strings"

// A command invokes a generator, like "tree --n 5".
// The regex restricts occurrences of curly-bracketed expressions
// to things like "tree --random --seed {seed:5} {name} {count}"
// - {seed} can occur at most once
// - {name} and {count} can occur any number of times
#command_args: =~"([^{}]|\\{(name|count|seed(:[0-9]+)?)\\})*"
#command:      C={
	!~"\\{seed.*\\{seed" // don't use seed twice
	_parts: strings.Fields(C)
	_parts: [#path, ...#command_args]
}

// Test cases and test groups allow configuration of solution, visualiser, and random salt.
#config: {
	// Path to solution starts with slash, such as "/submissions/accepted/foo.py"
	solution?: #filepath & =~"^/"
	// Visualiser can be omitted to disable visualisation, may not use {count}
	visualizer?:  #command & =~"^/" & !~"\\{count" | null
	random_salt?: string
}

#testgroup_config: {
	#config
	"testdata.yaml": #testdata_settings
}

#testcase:
	#command & !~"^/" |
	{
		generate?: #command & !~"^/"
		count?:    int & >=1 & <=100
		// The "copy" key uses a path relative to "/generators/" ending in a testcase name,
		// such as "manual/samples/3".
		copy?:                                    #dirpath
		["in" | "ans" | "out" | "desc" | "hint"]: string
		interaction?:                             =~"^([<>][^\\n]*\\n)+$"
		#config
	}

#data_dict: {[#name]: #testgroup | #testcase}
#data_list: {[#name | ""]: #testgroup | #testcase} & struct.MinFields(1) & struct.MaxFields(1)

#testgroup: {
	data?: #data_dict | [...#data_list]
	include?: [...#dirpath]
	#testgroup_config
}

#Generators: {
	// Generators are named like files or testcases, like "tree.py" or "a".
	// Each consists of a nonempty list of paths relative to "/generators/",
	// such as ["tree_generator/tree.py", "lib.py"].
	generators?: [#name]: [...(#path & !~"^/")] & [_, ...]
	data: close({
		sample!:          #testgroup
		secret!:          #testgroup
		invalid_input?:  #testgroup
		invalid_answer?: #testgroup
		invalid_output?: #testgroup
		valid_output?: #testgroup
	})
	#testgroup_config
	version: =~"^[0-9]{4}-[0-9]{2}$" | *"2025-02"

	... // Do allow unknown_key at top level for tooling
}
