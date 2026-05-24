#!/usr/bin/env bash
set -euo pipefail

CUE="${HOME}/go/bin/cue" # or just cue, but I need the most recent build
# Change names #Foo and %23Foo to DEFFoo. This is because some LSP
# implementations are confused about the URI fragment identifer syntax.
SED_PATTERN='s/(#|%23)([A-Za-z0-9_]+)/DEF\2/g'

export_schema() {
    local schema="$1"
    local output="$2"

    echo "Exporting $schema → $output"
    "$CUE" export --out jsonschema -e "$schema" \
	  | sed -E '
	      s/^ {4}"additionalProperties"/    "unevaluatedProperties"/
	      /^ {5,}"additionalProperties": false,?$/d
	    ' \
        > "$output"
}

export_schema '#Generators'      generators_yaml_schema.json
export_schema '#Problem'         problem_yaml_schema.json
export_schema '#test_group'      test_group_yaml_schema.json
export_schema '#SubmissionsJson' submissions_yaml_schema.json
