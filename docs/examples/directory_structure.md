# Directory Structure

```
Problem
├── 🗀 data
│   ├── 🗀 sample                //in git
│   │   ├── 🗎 1.in
│   │   ├── 🗎 1.ans
│   │   └── ...
│   └── 🗀 secret                // typically git ignored if generated
│       └── ...
├── 🗀 generators                // optional
│   ├── 🗀 manual                // raw .in files for manual testcases
│   ├── 🗀 <generator name>      // contains all files of the generator i.e. validate.h and main.cpp
│   ├── 🗎 generator.py          // single file generators don't need a directory
│   ├── ...
│   └── 🗎 generator.yaml
├── 🗀 input_validators          // only one checker is needed
│   ├── 🗀 <input_validator>     // contains all files of the checker i.e. validate.h and main.cpp
│   ├── 🗎 input_validator.viva  // viva checker
│   ├── 🗎 input_validator.ctd   // ctd checker
│   └── ...
├── 🗀 answer_validators          // BAPCtools extension, same as input_validators but for .ans files
│   └── ...
├── 🗀 statement
│   ├── 🗎 problem.en.tex        // statement
│   └── 🗎 figures.png           // figures for statement/solution/slides
├── 🗀 statement
│   └── 🗎 solution.tex          // solution slides (can reuse figures.png)
├── 🗀 problem_slide
│   └── 🗎 problem-slide.en.tex  // problem slides (can reuse figures.png)
├── 🗀 output_validator          // optional, contains all files if a custom output checker is needed
│   └── ...
├── 🗀 input_visualizer          // used to visualize test cases
│   └── ...
├── 🗀 output_visualizer         // used to visualize submission output
│   └── ...
├── 🗀 submissions               // submissions with expected results
│   ├── 🗀 accepted
│   │   └── ...
│   ├── 🗀 rejected
│   ├── 🗀 wrong_answer
│   ├── 🗀 time_limit_exceeded
│   ├── 🗀 run_time_error
│   ├── 🗀 brute_force
│   └── 🗎 submissions.yaml
└── 🗎 problem.yaml              // name author etc.
```
