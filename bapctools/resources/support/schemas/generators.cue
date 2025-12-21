package problempackageformat

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

// Test cases and test groups allow configuration of solution, and random salt.
#config: {
	// Path to solution starts with slash, such as "/submissions/accepted/foo.py"
	solution?:    #path & =~"^/"
	random_salt?: string
}

#test_group_config: {
	#config
	"test_group.yaml": #test_group_configuration
}

#test_case:
	#command & !~"^/" |
	{
		generate?: #command & !~"^/"
		// Produce multiple test cases, numbered 1 ,..., count.
		// If value is a list or range, use those numbers instead.
		count?:    int & >=1 & <=100 | [...int] | =~"^-?\\d+\\.\\.=-?\\d+$"
		// The "copy" key uses a path relative to "/generators/" ending in a test case name,
		// such as "manual/samples/3".
		copy?: #path & !~"^/"
		match?: string | [...string] | {
			in?: string | [...string]
			ans?: string | [...string]
		}

		["in" | "in.statement" | "in.download" |
			"ans" | "ans.statement" | "ans.download" |
				"out"]: string
		interaction?: =~"^([<>][^\\n]*\\n)+$"
		yaml?:        #test_case_configuration

		#config
	}

#data_dict: {[#name]: #test_group | #test_case}
#data_list: {[#name | ""]: #test_group | #test_case} & struct.MinFields(1) & struct.MaxFields(1)

#test_group: {
	data?: #data_dict | [...#data_list]
	include?: [...#path]
	#test_group_config
}

#Generators: {
	// Generators are named like files or test cases, like "tree.py" or "a".
	// Each consists of a nonempty list of paths relative to "/generators/",
	// such as ["tree_generator/tree.py", "lib.py"].
	generators?: [#name]: [...(#path & !~"^/")] & [_, ...]
	data: close({
		sample!:         #test_group
		secret!:         #test_group
		invalid_input?:  #test_group
		invalid_answer?: #test_group
		invalid_output?: #test_group
		valid_output?:   #test_group
	})
	#test_group_settings
	version: =~"^[0-9]{4}-[0-9]{2}$" | *"2025-12"

	... // Do allow unknown_key at top level for tooling
}
