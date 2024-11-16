schemadir="../../support/schemas"
all_valid_yaml=(../../doc ../problems valid_yaml)

any_failed=0

# Iterate over each .yaml file in the directory
for dir in "${all_valid_yaml[@]}"; do
    for file in $(find "$dir" -type f -name '*generators.yaml'); do
	    echo -n "Processing $file... "
	    output=$(cue vet "$file" $schemadir/*.cue -d "#Generators" 2>&1)
	    exit_code=$?
	    if [ $exit_code -eq 0 ]; then
		    echo -e "\033[0;32mOK\033[0m"
	    else
		    echo -e "\033[0;31mError\033[0m"
		    echo "Output from cue vet:"
		    echo "$output"
		    any_failed=1
		    fi	
	    done
done
for file in invalid_yaml/*generators.yaml; do
    echo -n "Processing $file... "
    output=$(cue vet "$file" $schemadir/*.cue -d "#Generators" 2>&1)
    exit_code=$?
    if [ $exit_code -eq 1 ]; then
	    echo -e "\033[0;32mOK (correctly rejected)\033[0m"
    else
	    echo -e "\033[0;31mIncorrectly accepted\033[0m"
	    any_failed=1
    fi	
done
if [ $any_failed -ne 0 ]; then
    echo "One or more cue vet commands failed." >&2
    exit 1
else
    echo "All cue vet commands completed successfully."
    exit 0
fi
