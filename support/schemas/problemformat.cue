package problemformat

// Schemas relevant for the problem package format specification.

// Names for testgroups and testcases are alphanumerical with internal
// underscores and hyphens; such as "huge", "make_tree", "3", or "connected_graph-01",
// but not "huge_" or "-2".
let basename = "([A-Za-z0-9][A-Za-z0-9_-]*[A-Za-z0-9]|[A-Za-z0-9])"
name: =~"^\(basename)$"

// Filenames are somewhat like names, but can also contain '.'
// and have length at least 2, such as "good-solution_02.py"
// but not "huge_" or "a".
let filename = "[A-Za-z0-9][A-Za-z0-9_.-]*[A-Za-z0-9]"

filepath: =~"^/?\(filename)(/\(filename))*$"
casepath: =~"^\(filename)(/\(basename))*$"

// Test data settings

#testdata_settings: {
	input_validator_flags?:  *"" | string | {[string]: string}
	output_validator_flags?: *"" | string
	grading?: {
		score?:       >0
		max_score?:   >0
		aggregation?: "sum" | "min"
		// run_samples?: bool
	}
}
