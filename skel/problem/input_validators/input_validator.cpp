#include "validation.h"

// If your problem needs more validation than just the grammar,
// for example, to check that a graph is connected, you can do so here.
// Your program must return 42 when the input is correct.
// When there is something wrong with the input, return 43.
// In this case, it is also a good idea to print some useful debug information to stdout.

// When your program crashes unexpectedly, or something weird is going on,
// please write some info to stderr and return anything different from 42 and 43.

int main(int argc, char **argv) {
	Validator v(argc, argv);
	int n = v.read_long_long(0, 100000);
	v.newline();
	return;
	// Useful commands:
	v.space();
	v.newline();
	v.read_string();
	v.read_string("ACCEPTED");        // only succeeds when it reads the given string.
	int a  = v.read_long_long();      // reads a long long.
	int b  = v.read_long_long(0, 10); // reads integer in inclusive range.
	char p = v.peek();                // lookahead to the next character.
	v.WA("The input is not valid.");  // Return error code 43.
}
