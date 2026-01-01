package problempackageformat

import "list"

import "time"

import uuidpkg "uuid"

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

// A test data group is a subdivision of `secret`

#test_data_group: =~"secret/\(name_regex)$"

#ProgrammingLanguage: "ada" | "algol68" | "apl" | "bash" | "c" | "cgmp" | "cobol" | "cpp" | "cppgmp" | "crystal" | "csharp" | "d" | "dart" | "elixir" | "erlang" | "forth" | "fortran" | "fsharp" | "gerbil" | "go" | "haskell" | "java" | "javaalgs4" | "javascript" | "julia" | "kotlin" | "lisp" | "lua" | "modula2" | "nim" | "objectivec" | "ocaml" | "octave" | "odin" | "pascal" | "perl" | "php" | "prolog" | "python2" | "python3" | "python3numpy" | "racket" | "ruby" | "rust" | "scala" | "simula" | "smalltalk" | "snobol" | "swift" | "typescript" | "visualbasic" | "zig"
#LanguageCode:        =~"^[a-z]{2,3}(-[A-Z]{2})?$"
#Type:                "pass-fail" | "scoring" | "multi-pass" | "interactive" | "submit-answer"

#Source: string | {
	name!: string
	url?:  string
}

#Person: string | {
	name!:   string
	email?:  string
	orcid?:  string
	kattis?: string
}

#Persons: #Person | [#Person, ...#Person]

#Problem: {
	problem_format_version!: *"2025-09" | =~"^[0-9]{4}-[0-9]{2}(-draft)?$" | "draft" | "legacy" | "legacy-icpc"

	type?: *"pass-fail" | #Type | [#Type, ...#Type]
	if (type & [...]) != _|_ {
		_policy: true &
			!(list.Contains(type, "scoring") && list.Contains(type, "pass-fail")) &&
			!(list.Contains(type, "multi-pass") && list.Contains(type, "submit-answer")) &&
			!(list.Contains(type, "interactive") && list.Contains(type, "submit-answer"))
	}

	name!: string | {[#LanguageCode]: string}

	uuid!: uuidpkg.Valid

	version?: string

	credits?: string | {
		authors!:                                                        #Persons
		["contributors" | "testers" | "packagers" | "acknowledgements"]: #Persons
		translators?: [#LanguageCode]: #Persons
	}

	source?: #Source | [#Source, ...#Source]
	license: *"unknown" | "public domain" | "cc0" | "cc by" | "cc by-sa" | "educational" | "permission"
	if license != "public domain" {
		rights_owner?: #Persons
		if license != "unknown" && (credits & string) == _|_ && credits.authors == _|_ && source == _|_ {
			rights_owner!: _
		}
	}

	embargo_until?: time.Format("2006-01-02") | time.Format("2006-01-02T15:04:05Z")

	limits?: {
		time_multipliers?: {
			ac_to_time_limit?:  float & >=1 | *2.0
			time_limit_to_tle?: float & >=1 | *1.5
		}
		time_limit?:                    (float | int ) & >0
		time_resolution?:               float & >0 | *1.0
		["memory" | "output" | "code"]: int & >0

		// Resource guarantees
		["compilation_time" | "compilation_memory" | "validation_time" | "validation_memory" | "validation_output"]: int & >0
		if (type & [...]) != _|_ {
			if (list.Contains(type, "multi-pass")) {
				validation_passes?: int & >=2 | *2
			}
		}
	}

	keywords?: [...string]

	languages?: *"all" | [#ProgrammingLanguage, ...#ProgrammingLanguage]

	allow_file_writing?: *false | true

	constants?: [=~"^[a-zA-Z_][a-zA-Z0-9_]*$"]: int | float | string | {
		value!:               int | float | string
		[string & !="value"]: string
	}
}

// Test data configuration
#test_case_or_group_configuration: {
	args?: [...string]
	input_validator_args?: [...string] | {[string]: [...string]}
	output_validator_args?: [...string]
	input_visualizer_args?: [...string]
	output_visualizer_args?: [...string]
	full_feedback?: bool
}

#test_case_configuration: {
	#test_case_or_group_configuration
	hint?:        string
	description?: string
}

#test_group_configuration: {
	#test_case_or_group_configuration
	max_score?:               int & >=0 | "unbounded"
	score_aggregation?:       "pass-fail" | "sum" | "min"
	static_validation_score?: int & >=0 | "pass-fail"
	if static_validation_score != _|_ {
		static_validator_args?: [...string]
	}
	require_pass?: "sample" | #test_data_group | [...("sample" | #test_data_group)]

}
