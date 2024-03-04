package problemformat


#filename: =~ "^[a-zA-Z0-9][a-zA-Z0-9_.-]*[a-zA-Z0-9]$"
#path: =~ "[a-zA-Z0-9_.-/]*"

#testdata_settings: {
	input_validator_flags?: *"" | string | { [string]: string }
	output_validator_flags?: *"" |string
	grading?: {
		score?: >0
		max_score?: >0
		aggregation?: "sum" | "min"
		}
}
