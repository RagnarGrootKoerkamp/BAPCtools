package problempackageformat

import (
	"list"
	"strings"
)

// Some entries permit metavariables like {files} which will be replaced
let metavars = "files|binary|mainfile|mainclass|Mainclass|memlim|path"

// Some metavariables are mutually exclusive
let exclusive_metavars = ["{mainfile}", "{mainclass}", "{Mainclass}", "{binary}"]
template_string: s={
	_unique: {
		for word in strings.Fields(s)
		if list.Contains(exclusive_metavars, word) {
			word
		}
	}
	=~"^(?:{(?:\(metavars))}|[^{}])*$"
}

#Languages: {
	// Language names must be lowercase and start with a letter, and can only contain letters and digits
	[=~"^[a-z][a-z0-9]*$"]: {
		name!:     string
		priority!: int
		files!:    string
		shebang?:  string
		compile?:  template_string
		run!:      template_string
	}
}

// All priorities must be different
#Languages: L={
	_allPrioritiesDifferent: list.UniqueItems & [
		for k, v in L {v.priority},
	]
}
