package problemformat

import "list"

#person: =~"^[^<]+(<[^>]+>)?$" // "Alice" or "Bob <bob@com>"

#verdict: "AC" | "WA" | "RTE" | "TLE"

let globbed_dirname = "[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,254}"
#globbed_dirpath: =~"^(\(globbed_dirname)/)*\(globbed_dirname)$" & !~ "\\*\\*"
let globbed_filename = "([a-zA-Z0-9_][a-zA-Z0-9_.-]{0,254}|\\*)"

#globbed_submissionpath: =~"^(\(globbed_dirname)/)*\(globbed_filename)$" & !~ "\\*\\*"
#Submissions: {
	[#globbed_submissionpath]: #submission
}

#submission: {
	language?: string
	entrypoint?: string
	author?: #person | [...#person]
	model_solution?: bool
	#expectation
	[=~"^(sample|secret|\\*)" & #globbed_dirpath]: #expectation
}

#expectation: {
	permitted?: [#verdict, ...#verdict] // only these verdicts may appear
	required?: [#verdict, ...#verdict] // at least one of these verdicts must appear
	score?: int | [int, int] & list.IsSorted(list.Ascending)
	message?: string
	use_for_timelmit?: false | "lower" | "upper"
}
