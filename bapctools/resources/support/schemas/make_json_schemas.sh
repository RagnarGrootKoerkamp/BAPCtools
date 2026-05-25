#!/usr/bin/env bash
set -euo pipefail

CUE="${HOME}/go/bin/cue" # or just cue, but I need the most recent build


export_schema() {
    local schema="$1"
    local output="$2"

    echo "Exporting $schema → $output"
    "$CUE" export --out jsonschema -e "$schema" > "$output"
}

export_schema '#Generators'      generators_yaml_schema.json
export_schema '#Problem'         problem_yaml_schema.json
export_schema '#test_group'      test_group_yaml_schema.json
export_schema '#SubmissionsJson' submissions_yaml_schema.json
