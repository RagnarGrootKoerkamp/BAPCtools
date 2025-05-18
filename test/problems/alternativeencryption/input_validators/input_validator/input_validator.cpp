#include "validation.h"

// Check the grammar of the input files.
// You should also check properties of the input.
// E.g., check that a graph is connected.

int main(int argc, char* argv[]) {
	InputValidator v(argc, argv);
	v.test_strings({"encrypt", "decrypt"}, "action");
	v.newline();
	int n = v.read_integer("n", 1, 1000);
	v.newline();
	for(int i = 0; i < n; i++) {
		v.read_string("s", 1, 100, "abcdefghijklmnopqrstuvwxyz");
		v.newline();
	}
}
