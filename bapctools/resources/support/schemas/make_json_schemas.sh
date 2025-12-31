cue export --out jsonschema -e '#Generators' \
| sed -E 's/#([A-Za-z0-9_]+)/\1/g' \
> test_schema.json
