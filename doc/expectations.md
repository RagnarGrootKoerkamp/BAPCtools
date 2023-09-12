# Expectations

This framework allows problem author to express their expecations for the behaviour of a submission on the test data.

## Test Case Verdict

The behaviour of a submission on a _single_ test case is summarised in a *verdict*.

The verdicts are

AC

: Accepted. The submission terminates successfully within the time limit and the output vaidator accepts the submission output.

WA

: The submission terminates successfully within the time limit, but the output validator rejects the submission output on this testcase.

TLE

: The submission does not terminate within the time limit.

RTE

: The submission aborts within the time limit with a runtime error.


## Common Expectations for a Submission


The expected behaviour of a submission on the test data often falls into a number of common classes:

accepted

: Every test case is `AC`.

wrong answer

: Every test case receives `AC` or `WA`;  _some_ test case receives `WA`.

time limit exceeded

: Every test case receives `AC` or `TLE`;  _some_ test case receives `TLE`.

runtime exception

: Every test case receives `AC` or `RTE`;  _some_ test case receives `RTE`.

does not terminate

: Every test case receives `AC`, `RTE`, or `TLE` (but not `WA`);  _some_ test case receives `RTE` or `TLE`.

not accepted

: Not every test case receives `AC`. This is the complement of _accepted_.

In general, an expecation consists of a set of _permitted_ verdicts and set of _required_ verdicts.

* All test case must receive one of the permitted verdicts. If no permitted verdicts are specified, _all_ verdicts are permitted.
* Some test case must receive one of the required verdicts. If no required verdicts are specified, _no_ verdict is required.

Thus, the common expectations above can be spelt out in terms of lists of verdicts.
For instance for the submission `mysubmission.cpp`:

```yaml
mysubmission.py: accepted
```

is the same as

```yaml
mysubmission.py:
  permitted: [AC]
```
Similarly, 

```yaml
mysubmission.py: time limit exceeded
```

is the same as

```yaml
mysubmission.py:
  permitted: [AC, TLE]
  required: [TLE]
```

## Specifying Expectations

Expectations for submissions can be provided for a group of submissions or a single submission in
a file `/submissions/expectations.yaml`.
Submission patterns match by prefix, so it is easy to specify the expected behaviour of submissions by placing them into various subdirectories of `/submissions`.
A common tradition is specified like this:

```yaml
accepted: accepted
wrong_answer: wrong answer
time_limit_exceeded: time limit exceeded
runtime_exception: runtime exception
```
This would associate the expectation “accepted” with the submission `/submissions/accepted/mysubmission.cpp`.
The flexibility of the expectations framework is that it is agnostic about directory names; for instance you can  your crashing submissions in `/submissions/run_time_error/` and put other requirements on the submissions in `/submissions/mixed/`:

```yaml
run_time_error: runtime exception
mixed:
  permitted: [AC, WA, TLE]
  required: [WA]
```

## Specification per Submission

The submission pattern is matches by prefix, so instead of directories you can specify individual submissions:

```yaml
mixed/alice.py
  permitted: [AC, WA, TLE]
  required: [WA]
mixed/bob.py
  permitted: [AC, WA, TLE]
  required: [TLE]
```

## Specification per Test Data

Top-level expectations apply to all test data, but you can be more fine-grained and specify expectations for subdirectories of `/data`.
For instance, if you want all submission in `wrong_answer` to pass the sample inputs, you’d write:

```yaml
wrong_answer:
  sample: accepted
  secret: accepted
```

# Schema

Here is the specification:

```cue
#registry

#registry: close({ [string]: #root })

#verdict: "AC" | "WA" | "RTE" | "TLE" 
#verdicts: [...#verdict]

#root: { 
    #expectations
    [=~"^(sample|secret)"]: #expectations
}

#expectations: {
    #common
    #range
    permitted?: #verdicts // only these verdicts may appear
    required?:  #verdicts // at least one of these verdicts must appear
    judge_message?: string // this judgemessage must appear
    score?: #range
    fractional_score?: #fractional_range
    }

#common: "accepted" |        // { permitted: AC; required: AC }
    "wrong answer" |         // { permitted: [AC, WA]; required: WA }
    "time limit exceeded" |  // { permitted: [AC, TLE]; required: TLE }
    "runtime exception" |    // { permitted: [AC, RTE]; required: RTE }
    "does not terminate" |   // { permitted: [AC, TLE, RTE}; required: [RTE, TLE]
    "not accepted" |         // { required: [RTE, TLE, WA] }
    "full score"             // { fractional_score: 1.0 }
    
#range: number | [number, number] 
#fractional_range: #fraction | [#fraction, #fraction]
#fraction: >= 0.0 | <= 1.0 | float
```

# Examples

```yaml
# Simple examples for some common cases

a.py: accepted            # AC on all cases
b.py: wrong answer        # at least one WA, otherwise AC
c.py: time limit exceeded # at least one TLE, otherwise AC
d.py: runtime exception   # at least one RTE, otherwise AC
e.py: does not terminate  # at least one RTE or TLE, but no WA
f.py: not accepted        # at least one RTE, TLE, or WA
g.py: full score          # gets max_score

# submission are identified by prefix:

wrong_answer/: wrong answer # expectations "wrong answer" apply to "wrong_answer/th.py" etc.

# Abbreviations are just shorthands for richer maps 
# of "required" and "permitted" keys.
#
# For instance, these are the same:

th.py: accepted
---
th.py:
  permitted: [AC]
  required: [AC]
---

# A submission failed by the output validator on some testcase
# These are the same:

wrong.py: wrong answer
---
wrong.py:
  permitted: [WA, AC]
  required: [WA]
---
wrong.py:
  permitted: # alternative yaml syntax for list of strings
    - WA
    - AC
  required: [WA]
---

# Specify that the submission fails, but passes the samples.
# These are the same, using the same abbreviations as
# above for "accepted" and "wrong answer"

wrong.py:
  sample: accepted
  secret: wrong answer
---
wrong.py:
  sample: 
    permitted: [AC]
    required: [AC]
  secret:
    permitted: [AC, WA]
    required: [WA]

# Constraints apply to testcases in entire subtree of cases that match the string:
funky.cpp:
  permitted: [AC, WA, RTE]
  secret:
      permitted: [AC, RTE, TLE] # TLE is forbidden at ancestor, so this makes no sense
  secret/small: accepted # more restrictive than ancestor: this is fine
          
# Specification for subgroups works "all the way down to the tescase"
# though it's seldomly needed:
funky.cpp:
  secret/huge_instances/disconnected_graph:
          permitted: [RTE, TLE]
          
# Can also specify a required judgemessage, not only verdicts
linear_search.py:
  judge_message: "too many rounds" # matches judgemessage.txt as substring, case-insensitive
  
# Allow digit regex to catch auto-numbered groups: `\d+`

submission:py
  secret/\d+-group/: accepted # matches 02-group

#########
# Scoring
#########

# simplest case:
th.py: full score

# Partial solutions can be given in various ways:
partial.py: [50, 60]
---
partial.py: 60
---
partial.py:
  score: 60
---
partial.py:
  score: [50, 60]
---
partial.py:
  fractional_score: [.5, .6] # percentage of full score
---
# For subtasks, you probably want to specify the
# outcome per subgroup. You need to be more verbose:
partial.py:
  secret/subtask1: full score
  secret/subtask2: 0
  secret/subtask3: 0
---
# Can be even more verbose about scores
partial.py:
  secret/subtask1: full score
  secret/subtask2:
        score: 13   # absolute score on this group is exactly 13
  secret/subtask3: # between 10% and 40% of (full score for subtask 3)
        fractional_score: [.1, .4] 
---
# Can still specify testcases
bruteforce.py:
  secret/subtask1: full score # subtask 1 has small instances
  secret/subtask2:
        score: 0      # No points for this subtask
        required: TLE # ... because some testcase timed out
        permitted: [AC, TLE] # ... rather than any WAs
---
# The common abbreviations work here as well, you probably want to write this instead:
bruteforce.py:
  secret/subtask1: full score # could write "accepted" as well in this case
  secret/subtask2: time limit exceeded # this is more informative than "0"
```
