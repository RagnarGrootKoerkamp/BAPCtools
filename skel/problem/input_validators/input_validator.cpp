#include "validation.h"

// Check the grammar of the input files.
// You should also check properties of the input.
// E.g., check that a graph is connected.
// TODO: Remove this comment, and summarize your input validator.

int main() {
	InputValidator v;
	int n = v.read_long_long(0, 100000);
	v.newline();
	return 0;

	// Other useful commands:
	v.space();
	v.newline();
	string s = v.read_string();
	v.read_string("ACCEPTED"); // only succeeds when it reads the given string.
	v.read_string(4, 5);     // only succeeds when it reads a string with length in inclusive range.
	v.read_long_long();      // reads a long long.
	v.read_long_long(0, 10); // reads integer in inclusive range.
	bool b = v.peek('x');    // test the next character.
	v.WA("The input is not valid."); // Print error and exit with code 43.

	// In its destructor, v automatically exits with code 42 here.
}
