# BAPC/NWERC Jury process

This WIP doc contains some remarks on things we do in the BAPC and NWERC jury.

## Ideal scoreboard

## Problem selection

## Schedule

## Random notes

- The head of jury must not be assigned a problem.
  Keeping track of all other problems is work enough.
- Head of jury should assign tasks to specific people, not ask 'who wants to do this'.

## Pre-contest checklist

- `bt constraints` to make sure that:
  - bounds in the statement
  - bounds in the validators
  - bounds in the actual test data
    are all the same, and that all bounds are actually reached by the test data.
- Run all C++ submissions with sanitizers enabled:
  - First regenerate all testcases
  - Then run
    ```
    bt run -G -m unlimited --cpp-flags=-fsanitize=undefined,address
    ```
