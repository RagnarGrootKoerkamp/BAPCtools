package problemformat

// cue version 0.6
// To validate generators.yaml using cue:
// > cue vet generators.yaml *.cue -d "#Generators"

import "struct"

#command: !="" & (=~"^[^{}]*(\\{(name|seed(:[0-9]+)?)\\}[^{}]*)*$")

#name: =~"^([[:alnum:]]|[[:alnum:]][[:alnum:]_-]*[[:alnum:]])$"
let filename = "[[:alnum:]][[:alnum:]_.-]*[[:alnum:]]"
#path: =~"^/\(filename)(/\(filename))*$"
#copypath: =~"^(\(filename)/)*(\(filename)|[[:alnum:]])$"

#file_config: {
	solution?:    #path 
	visualizer?:  #path | null
	random_salt?: string
}

#testcase:
	#command |
	{
		generate?:                        #command
		copy?:                            #copypath
		["in" | "ans" | "desc" | "hint"]: string
		#file_config
	} // same as generate: #command

#data: close({[#name | ""]: #testgroup | #testcase})

#data_dict: #data & close({[#name]: _}) // forbids name ""
#data_list: #data & struct.MinFields(1) & struct.MaxFields(1)

#testgroup: {
	"testdata.yaml"?: #testdata_settings
	data?:            #data_dict | [...#data_list]
	include?: [...#name]
	#file_config
}

#Generators: {
	generators?: [string]: [...string]
	#testgroup

	... // Do allow unknown_key at top level for tooling
}

#Generators: data: close({
	sample!:         #testgroup
	secret!:         #testgroup
	invalid_inputs?: #testgroup
})
