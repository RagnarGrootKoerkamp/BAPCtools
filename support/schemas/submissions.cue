package problemformat

import "list"

#person: =~"^[^<]+(<[^>]+>)?$" // "Alice" or "Bob <bob@com>"

#verdict: "AC" | "WA" | "RTE" | "TLE"

#testnode_pattern: =~"[a-zA-Z0-9_/\\*]+" // TODO
#Submissions: {
	language?:   string
	entrypoint?: string
	author?: #person | [...#person]
	#expectation
	[=~"^(sample|secret|\\*)" & #testnode_pattern]: #expectation
}

#expectation: {
	permitted?: [#verdict, ...#verdict] // only these verdicts may appear
	required?: [#verdict, ...#verdict] // at least one of these verdicts must appear
	score?: int | [int, int] & list.IsSorted(list.Ascending)
	use_for_timelmit?: false | "lower" | "upper"
}

// Play with me at https://cuelang.org/play/?id=3oy3DL9Hx5X#w=function&i=cue&f=eval&o=cue
