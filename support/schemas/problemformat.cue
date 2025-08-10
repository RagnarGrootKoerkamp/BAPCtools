package problemformat

// Directory names, as well as names of test cases and generators are
// alphanumerical with internal underscores and hyphens; such as
// "huge", "make_tree", "3", "a", or "connected_graph-01";
// but not "huge_" or "-2" or "bapc.24" or ".." or "".
let dirname = "[A-Za-z0-9]([A-Za-z0-9_-]{0,253}[A-Za-z0-9])?"
#name: =~"^\(dirname)$"

// Directory paths are separated by / and do not start with a slash
#dirpath: =~"^(\(dirname)/)*\(dirname)$"

// Filenames are names, but have length at least 2 and can also
// contain '.' such as "good-solution_02.py" or "1.in"
let filename = "[A-Za-z0-9][A-Za-z0-9_.-]{0,253}[A-Za-z0-9]"

#filepath: =~"^/?(\(dirname)/)*\(filename)$"

// Paths can both refer to objects like the test group "data/secret/huge" or
// a program file like "/submissions/accepted/x.cpp"

#path: #dirpath | #filepath
// Test data settings

#test_group_settings: {
	scoring?: {
		score?:       >0 | "unbounded"
		aggregation?: "sum" | "min"
		require_pass: string | [string]
	}
	input_validator_args?: *[] | [string] | {[string]: [string]}
	output_validator_args?: *[] | [string]
	test_case_visualizer_args?: *[] | [string]
	output_visualizer_args?: *[] | [string]
	static_validation?: *false | true | {
		args?: string
		score?: int
	}
	full_feedback?: bool
}
