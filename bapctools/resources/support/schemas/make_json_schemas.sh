#!/usr/bin/env bash
set -euo pipefail

CUE="cue"

export_schema() {
    local schema="$1"
    local output="$2"
    local instance="${3:-.}" # default: local package; pass a module path for ppf-owned schemas

    echo "Exporting $schema → $output"
    "$CUE" export "$instance" --out jsonschema -e "$schema" > "$output"
}

PPF_MODULE="github.com/thorehusfeldt/ppf-schemas/problempackageformat"

export_schema '#Generators'      generators_yaml_schema.json
export_schema '#Problem'         problem_yaml_schema.json  "$PPF_MODULE"
export_schema '#test_group'      test_group_yaml_schema.json
export_schema '#SubmissionsJson' submissions_yaml_schema.json
