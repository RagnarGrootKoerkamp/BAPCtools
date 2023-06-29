// Below is a formal [CUE](https://cuelang.org/docs/references/spec/)
// specification for the `generators.yaml` file with a root object `Generators`.
//
// The `...` in `generator` and `directory` indicate that additional keys
// unknown to the spec are allowed.
// The `generator_reserved` and `directory_reserved` objects indicate keys that
// work only for `generator`/`directory` and should not be reused in other places.

import "struct"

command: !="" & (=~"^[^{}]*(\\{(name|seed(:[0-9]+)?)\\}[^{}]*)*$")
file_config: {
	solution?:    command | null
	visualizer?:  command | null
	random_salt?: string
}
generator: command | {
	input: command
	file_config
	directory_reserved
	...
}

data_dict: [string]: directory | generator | null // ERROR: fails to match against ""

directory: {
	file_config
	"testdata.yaml"?: {
		...
	}
	data?: data_dict | [...{data_dict & struct.MaxFields(1)}]
	generator_reserved
	...
}
Generators: {
	generators?: {
		[string]: [...string]
	}
	directory
}
generator_reserved: {
	input?: _|_
	...
}
directory_reserved: {
	data?:            _|_
	include?:         _|_
	"testdata.yaml"?: _|_
	...
}
