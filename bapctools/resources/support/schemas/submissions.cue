package problempackageformat

import "list"

#verdict: "AC" | "WA" | "RTE" | "TLE"

#Submissions: {
	[#path]: #submission
}

#submission: {
	language?: string
	entrypoint?: string
	author?: #Persons
	model_solution?: bool
	#expectation
	[=~"^(sample|secret|\\*)" & #path]: #expectation
}

#expectation: {
	permitted?: [#verdict, ...#verdict] // only these verdicts may appear
	required?: [#verdict, ...#verdict] // at least one of these verdicts must appear
	score?: int | [int, int] & list.IsSorted(list.Ascending)
	message?: string
	use_for_timelmit?: false | "lower" | "upper"
}
