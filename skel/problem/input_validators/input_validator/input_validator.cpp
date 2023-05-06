#include "validation.h"

// Check the grammar of the input files.
// You should also check properties of the input.
// E.g., check that a graph is connected.

int main(int argc, char *argv[]) {
    InputValidator v(argc, argv);
    int n = v.read_integer("n", 0, 100000);
    v.space();
    float f = v.read_float("f", 0, 100000);
    v.newline();
    return 0;

    // Other useful commands:
    // read_{float,integer}[s] takes an optional tag:
    // Unique, Increasing, Decreasing, StrictlyIncreasing, StrictlyDecreasing
    v.read_integers("v", /*count=*/10, 0, 1000000, Unique);
    v.test_string("ACCEPTED"); // only succeeds when it reads the given string.
    v.read_string("s", 4, 5);     // only succeeds when it reads a string with length in inclusive range.
    bool b = v.peek('x'); // test the next character.
    v.WA("The input is not valid."); // Print error and exit with code 43.
    v.check(false, "WA on false");

    // In its destructor, v automatically exits with code 42 here.
    // TODO: Remove this comment, and summarize your input validator.
}
