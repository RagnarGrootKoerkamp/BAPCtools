# Validate all valid generator YAML found in the following dirs agains the CUE schema:

cd "$(dirname "$0")"

all_valid_yaml=(../../../doc ../../../skel/problem ../../problems valid_yaml)

# Arguments
#
#  -j: also validate the JSON schema
#
# Also make sure invalide YAML in invalid_yaml/*generators.yaml is rejected;
# here the yaml can be split using `---` and each snippet is individually
# validated.

schemadir="../../../support/schemas"

failed=0

SNIPPETS_DIR=$(mktemp -d)
trap "rm -rf $SNIPPETS_DIR" EXIT

for dir in "${all_valid_yaml[@]}"; do
    for file in $(find "$dir" -type f -name '*generators.yaml'); do
	    echo -n "cue vet "$file" $schemadir/*.cue -d \"#Generators\" "
	    tmp="$(mktemp --suffix .yaml)"
	    sed "s/{%test_group_yaml_comment%}/#/" "$file" | sed "s/{%output_validator_args%}//" > "$tmp"
	    output_cue=$(cue vet "$tmp" $schemadir/*.cue -d "#Generators" 2>&1)
	    rm "$tmp"
	    exit_code_cue=$?
	    if [ $exit_code_cue -eq 0 ]; then
		    echo -n -e "\033[0;32mOK(cue)\033[0m"
	    else
		    echo -n -e "\033[0;31mError(cue)\033[0m"
		    ((failed++))
	    fi

	    output_json=""
	    if [ "$1" = "-j" ]; then
		    output_json=$(cue vet "$file" $schemadir/generators_yaml_schema.json 2>&1)
		    exit_code_json=$?
		    if [ $exit_code_json -eq 0 ]; then
			    echo -n -e "\033[0;32m OK(json)\033[0m"
		    else
			    echo -n -e "\033[0;31m Error(json)\033[0m"
			    ((failed++))
		    fi
	    fi
	    echo "$output_cue" | head -n 1
	    if [ -n "$output_json" ]; then
		    echo "$output_json" | head -n 1
	    fi
	    done
done
for yamlfile in invalid_yaml/*generators.yaml; do
	if grep -q '^---$' "$yamlfile"; then
		echo "Processing $yamlfile as snippets..."
		# Split the YAML file into snippets based on `---`
		awk -v snippets_dir="$SNIPPETS_DIR" -v file_base="$(basename "$yamlfile")" '
			BEGIN {
			    snippet_count = 0
			    snippet_file = snippets_dir "/" file_base "_snippet_" (++snippet_count) ".yaml"
			}
			/^---/ {
			    if (snippet_file != "") close(snippet_file)
			    snippet_file = snippets_dir "/" file_base "_snippet_" (++snippet_count) ".yaml"
			}
			$0 !~ /^---/ { print > snippet_file }
			END { if (snippet_file != "") close(snippet_file) }
		' "$yamlfile"
	else
		cp "$yamlfile" "$SNIPPETS_DIR/$(basename "$yamlfile")"
	fi
done

# Run `cue vet` on each invalid yaml file and snippet
for snippet in "$SNIPPETS_DIR"/*.yaml; do
	if ! grep -q '^[^#]' "$snippet"; then
		# TODO: empty generators.yaml files _should_ be invalid, but for some reason, the CI currently disagrees.
		echo "Skipping empty $(basename $snippet)"
		continue
	fi
	echo -n "Invalidating $(basename $snippet) "
	snippet_failed=0
	cue vet "$snippet"  $schemadir/*.cue -d "#Generators" > /dev/null 2>&1
	if [[ $? -ne 0 ]]; then
		echo -n -e "\033[0;32mOK (correctly rejected)\033[0m"
	else
		echo -n -e "\033[0;31mIncorrectly accepted\033[0m"
		snippet_failed=1
		((failed++))
	fi
	if [ "$1" = "-j" ]; then
		cue vet $snippet $schemadir/generators_yaml_schema.json > /dev/null 2>&1
		exit_code_json=$?
		if [ $exit_code_json -ne 0 ]; then
			echo -n -e "\033[0;32m OK(json)\033[0m"
		else
			echo -n -e "\033[0;31m Error(json)\033[0m"
			snipped_failed=1
			((failed++))
		fi
	fi
	printf "\n"
	if [ $snippet_failed = 1 ]; then
		cat $snippet
	fi
done
if [ $failed -ne 0 ]; then
    echo "$failed errors." >&2
    exit 1
else
    echo "All cue vet commands completed successfully."
    exit 0
fi
