@experiment(explicitopen)

package problempackageformat

import "list"

import "time"

import uuidpkg "uuid"

#Type:                "pass-fail" | "scoring" | "multi-pass" | "interactive" | "submit-answer"

#Source: string | {
	name!: string
	url?:  string
}

#Person: string | {
	// The person's name, such as `Josiah Carberry`
	name!: string

	// The person's email address, such as `jcarberry@brown.edu`
	email?: string

	// The person's ID in the Open Researcher and Contributor ID system, such as `0000-0002-1825-0097`
	orcid?: string

	// The person's username on Kattis, such as `jcarberry01`
	kattis?: string
}

#Persons: #Person | [#Person, ...#Person]

#Problem: {
	// The version of the problem format package used for this problem.
	problem_format_version!: "2025-09" | "legacy"

	// A universally unique identifier for this problem, such as `acde070d-8c4c-4f0d-9d8a-162843c10333`.
	uuid?: uuidpkg.Valid

	// Keywords describing this problem, such as "graph", "dynamic programming", or "greedy".
	// These are not standardized and are only for informational purposes.
	keywords?: [...string]

	// The name of the problem.
	name!: _

	// The type of this problem.
	type?: _

	// Keywords describing this problem, such as "greedy".
	keywords?: _

	// The license under which this problem may be used.
	license?: *"unknown" | "public domain" | "cc0" | "cc by" | "cc by-sa" | "educational" | "permission"

	#Problem_2025_09... | #Problem_legacy...

	limits?: {
		["memory" | "output" | "code" | "compilation_time" | "compilation_memory" | "validation_time" | "validation_memory" | "validation_output"]: int & >0

		if (type & [...]) != _|_ if (list.Contains(type, "multi-pass")) {
				validation_passes?: int & >=2 | *2
			}

	}
}

#Problem_2025_09: {
	problem_format_version: "2025-09"

	uuid!: _

	// The name field is a map of language codes to problem names.
	// The set of languages for which name is given must exactly match the set of languages for which a problem statement exists.
	name!: string | {[#LanguageCode]: string}

	// The type of this problem, such as "pass-fail" or ["scoring", "interactive"]
	type?: *"pass-fail" | #Type | [#Type, ...#Type]
	if (type & [...]) != _|_ {
		_policy: true &
			!(list.Contains(type, "scoring") && list.Contains(type, "pass-fail")) &&
			!(list.Contains(type, "multi-pass") && list.Contains(type, "submit-answer")) &&
			!(list.Contains(type, "interactive") && list.Contains(type, "submit-answer"))
	}

	// The version of this problem, as it undergoes (slight) changes possibly during development or deployment.
	// This can be used to check whether a problem uploaded to a contest system needs to be updated since it does not contain the latest fixes.
	version?: string

	// Keywords describing the problem, such as ["graph", "dynamic programming"].
	keywords?: [...string]

	// The persons who should get credit for this problem.
	credits?: string | {

		// The author(s) of this problem.
		authors!: #Persons

		// The people who developed the problem package, such as the statement, validators, and test data.
		contributors?: #Persons

		// The people who tested the problem package, for example, by providing a solution and reviewing the statement.
		testers?: #Persons

		//The people who translated the statement to other languages.
		translators?: [#LanguageCode]: #Persons

		// The people who created the problem package out of an existing problem description.
		packagers?: #Persons

		// Acknowledgements or special to persons who helped with this problem.
		acknowledgements?: #Persons
	}

	license: _
	if license != _|_
		if license != "public domain" {
			// The person(s) owning the rights to this problem.
			rights_owner?: #Persons
			if license != "unknown" && (credits & string) == _|_ && credits.authors == _|_ && source == _|_ {
				rights_owner!: _
			}
		}


	// The source(s) of this problem, such as `Northwestern Europe Regional Contest (NWERC) 2005`.
	source?: #Source | [#Source, ...#Source]

	limits?: {
		time_multipliers?: {
			ac_to_time_limit?:  number & >=1 | *2.0
			time_limit_to_tle?: number & >=1 | *1.5
		}
		time_limit?:      (float | int ) & >0
		time_resolution?: float & >0 | *1.0
	}


	embargo_until?: time.Format("2006-01-02") | time.Format("2006-01-02T15:04:05Z")

	languages?: *"all" | [#ProgrammingLanguage, ...#ProgrammingLanguage]

	allow_file_writing?: *false | true

	constants?: [=~"^[a-zA-Z_][a-zA-Z0-9_]*$"]: int | float | string | {
		value!:               int | float | string
		[string & !="value"]: string
	}
}

#Problem_legacy: {
	problem_format_version: "legacy"

	name!: string

	type?: "pass-fail" | "scoring"

	// The person or persons credited as author(s) of this problem.  Given as a string
	// separated by "," or "and ". This would typically be the people that came up with
	// the idea, wrote the problem specification and created the test data. This is sometimes
	// omitted when authors choose to instead only give source credit, but both may be specified.
	author?: string

    // Who should get source credit. This would typically be the name (and year) of the event
	// where the problem was first used or created for.

	source?: string
	if source != _|_ {
		source_url?: string
	}

	limits?: {
		time_multiplier?:  number & >0 | *5
		time_safety_margin?: number & >0 | *2
	}

	// Validation is a space separated list of strings describing how validation is done.
	// Must begin with one of "default" or "custom".
	validation?: string

	// Validator_flags are passed directly to the output validator.
	validator_flags?: string

	if type != _|_ if type == "scoring" {
		grading?: {
			objective?: "min" | "max"
			show_test_data_groups?: bool
		}
	}

	keywords?: string
}
