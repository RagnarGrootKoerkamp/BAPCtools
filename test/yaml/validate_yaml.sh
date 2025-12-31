#!/usr/bin/env bash
#set -euo pipefail

cd "$(dirname "$0")"

# ----------------------------
# Configuration
# ----------------------------

all_valid_yaml=(../../doc ../problems problem/valid_yaml generators/valid_yaml test_group/valid_yaml)
all_invalid_yaml=(generators/invalid_yaml problem/invalid_yaml test_group/invalid_yaml)
schemadir="../../bapctools/resources/support/schemas"


# Temp directory for snippets
SNIPPETS_DIR=$(mktemp -d)
trap "rm -rf $SNIPPETS_DIR" EXIT

# Fail-fast mode if -e is passed
# Shut up about ignored .yaml
FAIL_FAST=0
SILENT=0
VERBOSE=0
for arg in "$@"; do
	case "$arg" in
		-e) FAIL_FAST=1 ;;
		-s) SILENT=1 ;;
		-v) VERBOSE=1 ;;
	esac
done

failed=0
succeeded=0
ignored=0

# ----------
# Dispatcher
# ----------

declare -A schema_map=(
["*generators.yaml"]="#Generators"
["*problem.yaml"]="#Problem"
["*test_group.yaml"]="#test_group_configuration"
# add more schemas here
)

schema_for_file() {
	local file=$1
	for pattern in "${!schema_map[@]}"; do
		if [[ $file == $pattern ]]; then
			echo "${schema_map[$pattern]}"
			return 0
		fi
	done
	return 1
}

# --------------
# Cue vet helper
# --------------
run_cue_vet() {
	local snippet=$1
	local schema=$2
	local parent_file=${3:-$(basename "$snippet")}
	local expect_failure=${4:-0}

	echo -n "Validating $(basename "$snippet") (schema=$schema) "

	output_cue=$(cue vet "$schemadir" "$snippet" -d "$schema" 2>&1)
	exit_code=$?

	if [ $exit_code -eq 0 ]; then
		if [ "$expect_failure" -eq 1 ]; then
			echo -e "\033[0;31mIncorrectly accepted (should fail)\033[0m"
			sed 's/^/    /' <<< "$output_cue"
			((failed++))
			if [ "$VERBOSE" -eq 1 ]; then
				cat $snippet
			fi
			[ "$FAIL_FAST" -eq 1 ] && exit 1
		else
			echo -e "\033[0;32mOK\033[0m"
			((succeeded++))
		fi
	else
		if [ "$expect_failure" -eq 1 ]; then
			echo -e "\033[0;32mOK (correctly rejected)\033[0m"
			if [ "$VERBOSE" -eq 1 ]; then
				echo -e "$output_cue" | head -1
			fi
			((succeeded++))
		else
			echo -e "\033[0;31mError\033[0m"
			sed 's/^/    /' <<< "$output_cue"
			((failed++))
			[ "$FAIL_FAST" -eq 1 ] && exit $exit_code
		fi
	fi
}

# ------------------------
# Process single YAML file
# ------------------------
process_yaml_file() {
	local file=$1
	local expect_failure=${2:-0}  # default: 0 = normal
	local schema
	if ! schema=$(schema_for_file "$file"); then
		[ "$SILENT" -eq 0 ] && echo -e "\033[0;33mSkipping $(basename "$file") — no schema defined yet.\033[0m"
		((ignored++))
		return 0
	fi

	if grep -q '^---$' "$file"; then
		snippet_count=0
		awk -v snippets_dir="$SNIPPETS_DIR" -v file_base="$(basename "$file")" '
		BEGIN { snippet_count = 0 }
		/^---$/ { snippet_count++; next }
		{
			snippet_file = snippets_dir "/" file_base "_snippet_" snippet_count ".yaml"
			print > snippet_file
		}
		' "$file"

		for snippet in "$SNIPPETS_DIR"/"$(basename "$file")"_snippet_*.yaml; do
			run_cue_vet "$snippet" "$schema" "$file" "$expect_failure"
			rm -f "$snippet"
		done
	else
		run_cue_vet "$file" "$schema" "" "$expect_failure"
	fi
}

# -----------------------
# Validate all valid YAML
# -----------------------
for dir in "${all_valid_yaml[@]}"; do
	while read -r file; do
		process_yaml_file "$file"
	done < <(find "$dir" -type f -name '*.yaml')
done

# ------------------------------------------
# Invalidate invalid YAML (expect rejection)
# ------------------------------------------
for dir in "${all_invalid_yaml[@]}"; do
	while read -r file; do
		process_yaml_file "$file" 1
	done < <(find "$dir" -type f -name '*.yaml')
done

# -------
# Summary
# -------
echo "" 
echo -e "\033[1mSummary:\033[0m" 
printf " %-15s %s\n" "Succeeded:" "$succeeded" 
printf " %-15s %s\n" "Failed:" "$failed" 
printf " %-15s %s\n" "Ignored:" "$ignored" 
echo ""

if [ $failed -ne 0 ]; then
	echo -e "\nTotal failed: $failed"
	exit 1
else
	echo -e "\nAll validations passed."
fi
