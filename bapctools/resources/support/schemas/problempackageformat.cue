@experiment(explicitopen)

package problempackageformat

// Directory and file names, as well as names of test cases are
// alphanumerical with internal underscores and hyphens; such as
// "huge", "make_tree", "3", "a", or "connected_graph-01";
// but not "-2" or ".2" or ".." or "".
let name_regex = "[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,254}"

#name: =~"^\(name_regex)$"

// Paths are separated by /,  they may start with (but not end with) /.
// Paths can both refer to objects like the test group "data/secret/huge" or
// a program file like "/submissions/accepted/x.cpp"
#path: =~"^/?(\(name_regex)/)*\(name_regex)$"

#absolute_path: #path & =~"^/"
#relative_path: #path & !~"^/"

// A test data group is a subdivision of `secret`


#test_data_group: =~"secret/\(name_regex)$"

#ProgrammingLanguage: "ada" | "algol68" | "apl" | "bash" | "c" | "cgmp" | "cobol" | "cpp" | "cppgmp" | "crystal" | "csharp" | "d" | "dart" | "elixir" | "erlang" | "forth" | "fortran" | "fsharp" | "gerbil" | "go" | "haskell" | "java" | "javaalgs4" | "javascript" | "julia" | "kotlin" | "lisp" | "lua" | "modula2" | "nim" | "objectivec" | "ocaml" | "octave" | "odin" | "pascal" | "perl" | "php" | "prolog" | "python2" | "python3" | "python3numpy" | "racket" | "ruby" | "rust" | "scala" | "simula" | "smalltalk" | "snobol" | "swift" | "typescript" | "visualbasic" | "zig"
#LanguageCode:        =~"^[a-z]{2,3}(-[A-Z]{2})?$"


// Test data configuration
#test_case_or_group_configuration: {
	args?: [...string]
	answer_validator_args?: [...string] | {[string]: [...string]}
	input_validator_args?: [...string] | {[string]: [...string]}
	output_validator_args?: [...string]
	input_visualizer_args?: [...string]
	output_visualizer_args?: [...string]
	full_feedback?: bool
}

#test_case_configuration: {
	#test_case_or_group_configuration...
	hint?:        string
	description?: string
}

#test_group_configuration: {
	#test_case_or_group_configuration...
	max_score?:               int & >=0 | "unbounded"
	score_aggregation?:       "pass-fail" | "sum" | "min"
	static_validation_score?: int & >=0 | "pass-fail"
	if static_validation_score != _|_ {
		static_validator_args?: [...string]
	}
	require_pass?: "sample" | #test_data_group | [...("sample" | #test_data_group)]

}
