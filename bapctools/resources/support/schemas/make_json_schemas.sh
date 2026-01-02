# As of cue 0.15, we need to change #Definition to Definition to avoid convusing URI snippet syntax
# Presumeably, this will change with a future CUE update, so the `sed` call will be redundant
cue export --out jsonschema -e '#Generators' | sed -E 's/#([A-Za-z0-9_]+)/\1/g' > generators_yaml_schema.json
cue export --out jsonschema -e '#Problem' | sed -E 's/#([A-Za-z0-9_]+)/\1/g' > problem_yaml_schema.json
cue export --out jsonschema -e '#test_group' | sed -E 's/#([A-Za-z0-9_]+)/\1/g' > test_group_yaml_schema.json
