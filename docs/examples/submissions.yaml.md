# `submissions.yaml`

This file is located under `problem_name/submissions/submissions.yaml`
The full specification can be found here [here](https://icpc.io/problem-package-format/spec/2025-09.html#example-submissions).

```yaml
# define some metadata for a submission
accepted/solution.py:
  language: python3
  entrypoint: solution.py
  authors: Author
  model_solution: False

# stronger requirements for a WA submission
wrong_answer/edge_case.py:
  sample:
    required: [AC]

# custom directory
ac_or_wa:
  permitted: [AC, WA]

# The following are the default directories and there configurations

# All cases must be accepted.
accepted:
  permitted: [AC]

# At least one case is not accepted.
rejected:
  required: [RTE, TLE, WA]

# All cases AC or WA, at least one WA.
wrong_answer:
  permitted: [AC, WA]
  required: [WA]

# All cases AC or TLE, at least one TLE.
time_limit_exceeded:
  permitted: [AC, TLE]
  required: [TLE]

# All cases AC or RTE, at least one RTE.
run_time_error:
  permitted: [AC, RTE]
  required: [RTE]

# Must not WA, but fail at least once.
# Note that by default these are not used for determining the time limit.
brute_force:
  permitted: [AC, RTE, TLE]
  required: [RTE, TLE]
```
