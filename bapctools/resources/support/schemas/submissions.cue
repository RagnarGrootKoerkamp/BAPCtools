package problempackageformat

import "list"

#verdict: "AC" | "WA" | "RTE" | "TLE"

// Regular expressions for glob-like path matching
let letter = "[a-zA-Z0-9_.*-]"
let word_re = "[a-zA-Z0-9_. -]*"
let brace_atom_re  = "\\{\(word_re)(,\(word_re))*\\}"
let component_re = "(\(letter)|\(brace_atom_re))+"
let glob_path = =~"^(\(component_re)/)*\(component_re)$" & !~"\\*\\*"

#Submissions: {
	[glob_path]: #submission
}

#submission: {
	language?: string
	entrypoint?: string
	authors?: #Persons
	model_solution?: bool
	#expectation
	[=~"^(sample|secret|\\*)" & glob_path]: #expectation
}

#expectation: {
	permitted?: [#verdict, ...#verdict] // only these verdicts may appear
	required?: [#verdict, ...#verdict] // at least one of these verdicts must appear
	score?: int | [int, int] & list.IsSorted(list.Ascending)
	message?: string
	use_for_time_limit?: false | "lower" | "upper"
}
