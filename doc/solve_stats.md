Clone https://github.com/hex539/scoreboard
Example command to create files:

```
bazel run analysis:activity -- --url https://chipcie.ch.tudelft.nl --contest 5 --prefreeze  -l ragnar -p {password} {contest_root}/solve_stats
bazel run analysis:activity -- --url https://chipcie.ch.tudelft.nl --contest 5 --prefreeze  -l ragnar -p {password} --solvestats > {contest_root}/solve_stats/problem_stats.tex

```
