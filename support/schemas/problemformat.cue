package problemformat

// Schemas relevant for the problem package format specification.
problem_package_format: string | *"legacy"



// Test data settings

#testdata_settings: {
	input_validator_flags?: *"" | string | {[string]: string}
	output_validator_flags?: *"" | string
	grading?: {
		score?:       >0
		max_score?:   >0
		aggregation?: "sum" | "min"
		// run_samples?: bool
	}
}
