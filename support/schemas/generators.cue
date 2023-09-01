package problemformat

// cue version 0.6
// To validate generators.yaml using cue:
// > cue vet generators.yaml *.cue -d "#Generators"

import "struct"

#command: !="" & (=~"^[^{}]*(\\{(name|seed(:[0-9]+)?)\\}[^{}]*)*$")
#name:    =~"^([A-Za-z0-9]{1,2}|[A-Za-z0-9][A-Za-z0-9_-]*[A-Za-z0-9])$"
#path: string

#file_config: {
	solution?:    #command
	visualizer?:  #command | null
	random_salt?: string
}

#testcase:
	#command | // same as generate: #command
	{
		generate?:                        #command
		copy?:                            #path
		["in" | "ans" | "desc" | "hint"]: string
		#file_config
	} 

#data: close({[#name | ""]: #testgroup | #testcase})

#data_dict: #data & close({[#name]: _}) // forbids name ""
#data_list: #data & struct.MinFields(1) & struct.MaxFields(1)

#testgroup: {
	"testdata.yaml"?: #testdata_settings // TODO should this field be called testdata_settings or settings?
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
