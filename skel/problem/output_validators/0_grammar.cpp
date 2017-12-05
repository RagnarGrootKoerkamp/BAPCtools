#include "grammar.h"
#include <fstream>

// This checks the grammar of the team output, so that we can safely pass it
// to the actual validator.
// Should return 42 on success and 43 on WA.
// In case of WA, write some useful feedback to stdout.
// When something unexpected happens, write to stderr and return something different from 42 and 43.

// Checking should be lenient with whitespace and case insensitive.

// Called as `./grammar [test.in test.ans feedbackdir] < team.out`.

int main(int arcg, const char *args[]) {
	std::ifstream ans(args[2]);

	int expected;
	ans >> expected;

	int output = read_long_long(0, 1000000);

	if(output != expected) WA(expected, output);

	// Always check whether the end of file has been reached.
	eof();
	return ret_AC;
}
