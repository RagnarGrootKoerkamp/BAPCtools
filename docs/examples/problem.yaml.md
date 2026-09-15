# `problem.yaml`

This file is located under `problem_name/problem.yaml`
The full specification can be found [here](https://icpc.io/problem-package-format/spec/2025-09.html).

```yaml
problem_format_version: 2025-09

name:
  en: Englidh Name
  de: German Name

uuid: 00000000-0000-0000-0000-000000000000

# 'pass-fail', 'interactive', 'multi-pass', or 'interactive multi-pass'
type: pass-fail

credits:
  # all entries can be a single name (string) or a list of names
  authors: Author Name
  contributors: []
  translators: []
  testers: []
  packagers: []
  acknowledgements: []

source: Example Contest
source_url: https://url.example
license: cc by-sa

# the shown limits are the defaults
limits:
  time_multipliers:
    ac_to_time_limit: 2.0
    time_limit_to_tle: 1.5
  # or a fixed time limit
  # time_limit: 1.0
  time_resolution: 1.0
  memory: 2048
  output: 8
  code: 128
  compilation_time: 60
  compilation_memory: 2048
  validation_time: 60
  validation_memory: 2048
  validation_output: 8
```
