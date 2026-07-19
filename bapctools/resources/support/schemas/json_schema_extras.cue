package bapctools

import ppf "github.com/thorehusfeldt/ppf-schemas/problempackageformat"

// JSON-export-only relaxation of ppf.#Submissions's regex-keyed map (glob_path), which
// `cue export --out jsonschema` still can't represent usefully -- it degrades to a bare
// "additionalProperties: true". Used only by make_json_schemas.sh, never by cue vet. Lived in
// ppf-schemas itself as #SubmissionsJson before v0.1.2; moved here since it's tooling, not
// spec vocabulary.
#SubmissionsJson: {
	[string]: {
		ppf.#submission
		[string]: ppf.#expectation
	}
}
