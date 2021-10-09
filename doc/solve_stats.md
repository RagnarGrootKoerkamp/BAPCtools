Clone https://github.com/hex539/scoreboard
Example command to create files:
```
bazel run analysis:activity -- --url https://chipcie.ch.tudelft.nl --contest 5 --prefreeze  -l ragnar -p <pass> ~b/main/solve_stats 
bazel run analysis:activity -- --url https://chipcie.ch.tudelft.nl --contest 5 --prefreeze  -l ragnar -p <pass> --solvestats > ~b/main/solve_stats/problem_stats.tex

```
