package problemformat

import "list"

#person: =~"^[^<]+(<[^>]+>)?$" // "Alice" or "Bob <bob@com>"

#verdict: "AC" | "WA" | "RTE" | "TLE"

let globbed_dirname = "[A-Za-z0-9*]([A-Za-z0-9_*-]{0,253}[A-Za-z0-9*])?"
#globbed_dirpath: =~"^(\(globbed_dirname)/)*\(globbed_dirname)$" & !~ "\\*\\*"
let globbed_filename = "([A-Za-z0-9*][A-Za-z0-9_.*-]{0,253}[A-Za-z0-9*]|\\*)"

#globbed_submissionpath: =~"^(\(globbed_dirname)/)*\(globbed_filename)$" & !~ "\\*\\*"
#Submissions: {
	[#globbed_submissionpath]: #submission
}

#submission: {
	language?:   string
	entrypoint?: string
	author?: #person | [...#person]
	#expectation
	[=~"^(sample|secret|\\*)" & #globbed_dirpath]: #expectation
}

#expectation: {
	permitted?: [#verdict, ...#verdict] // only these verdicts may appear
	required?: [#verdict, ...#verdict] // at least one of these verdicts must appear
	score?: int | [int, int] & list.IsSorted(list.Ascending)
	use_for_timelmit?: false | "lower" | "upper"
}

// Play with me at https://cuelang.org/play/?id=3oy3DL9Hx5X#w=function&i=cue&f=eval&o=cue
