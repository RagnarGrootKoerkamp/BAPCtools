#!/usr/bin/env python3
#
# Testing tool for the XXX problem  # TODO update name
#
# Usage:
#
#   python3 testing_tool.py -f inputfile <program invocation>
#
#
# Use the -f parameter to specify the input file, e.g. 1.in.
# The input file should contain the following:
# - The first line contains "encrypt".
# - The second line contains an integer n, the number of strings.
# - The following n lines each contain one string to encrypt.

# You can compile and run your solution as follows:

# C++:
#   g++ solution.cpp
#   python3 testing_tool.py -f 1.in ./a.out

# Python:
#   python3 testing_tool.py -f 1.in python3 ./solution.py

# Java:
#   javac solution.java
#   python3 testing_tool.py -f 1.in java solution

# Kotlin:
#   kotlinc solution.kt
#   python3 testing_tool.py -f 1.in kotlin solutionKt


# The tool is provided as-is, and you should feel free to make
# whatever alterations or augmentations you like to it.
#
# The tool attempts to detect and report common errors, but it is not an exhaustive test.
# It is not guaranteed that a program that passes this testing tool will be accepted.


import argparse
import subprocess
import traceback

parser = argparse.ArgumentParser(description="Testing tool for problem XXX.")  # TODO update name
parser.add_argument(
    "-f",
    dest="inputfile",
    metavar="inputfile",
    default=None,
    type=argparse.FileType("r"),
    required=True,
    help="The input file to use.",
)
parser.add_argument("program", nargs="+", help="Invocation of your solution")

args = parser.parse_args()


def single_pass(action: str, words: list[str]) -> list[str]:
    with (
        subprocess.Popen(
            " ".join(args.program),
            shell=True,
            stdout=subprocess.PIPE,
            stdin=subprocess.PIPE,
            universal_newlines=True,
        ) as p,
    ):
        assert p.stdin is not None and p.stdout is not None

        raw = "\n".join([action, str(len(words)), *words])
        stdout, stderr = p.communicate(input=raw)
        output = [line.strip() for line in stdout.strip().split("\n") if line.strip()]

        assert len(output) == len(words), (
            f"Your submission printed {len(output)} words, expected {len(words)} words"
        )
        print(f"{action} exit code: {p.returncode}")
        print(f"{action} output:")
        print()
        print(stdout, flush=True)

        for word_a, word_b in zip(words, output):
            assert len(word_a) == len(word_b), (
                f"Your submission changed the length of '{word_a}', you printed '{word_b}'"
            )

            for i, (char_a, char_b) in enumerate(zip(word_a, word_b), start=1):
                assert char_a != char_b, (
                    f"Letter at position {i} ({char_a}) is the same: '{word_a}' => '{word_b}'"
                )

        return output


try:
    with args.inputfile as f:
        # Parse input
        lines = [line.strip() for line in f.readlines()]
        action = lines[0]
        n = int(lines[1])
        words = lines[2:]

        assert action == "encrypt", f"Initial action must be 'encrypt', but got {action}"

    encrypted = single_pass("encrypt", words)
    decrypted = single_pass("decrypt", encrypted)

    for expected, got in zip(words, decrypted):
        assert expected == got, f"Got decrypted word '{got}', expected '{expected}'"

    print("Success.")

except AssertionError as e:
    print()
    print(f"Error: {e}")
    print()
    exit(1)

except Exception:
    print()
    print("Unexpected error:")
    traceback.print_exc()
    print()
    exit(1)
