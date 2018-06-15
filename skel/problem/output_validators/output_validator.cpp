#include "validation.h"

// Check the correctness of the answer here.

// For default output validation, where the team output is directly compared to the .ans,
// this script is called as:
//		output_validator input < answer
//
// Please validate:
//	- the syntax/grammar of the answer file.
//	- optionally, the correctness of the answer.

// For custom output validation, this is called as:
//		output_validator input answer < team_output
//
// Please validate:
//	- The syntax/grammar of the team output.
//	- The correctness of the team output.

// Please use the Validator class for validation.
// Examples below.
// TODO: Remove these comments, and summarize your output validator.

int main(int argc, char **argv) {
	// Set up the input and answer streams.
	std::ifstream in(argv[1]);
	// std::ifstream ans(argv[2]); // Only for custom checker.
	Validator v(argc, argv);

	int input;
	in >> input;
	int answer = v.read_long_long(input, input);
	v.newline();

	// Other useful commands:
	v.space();
	v.newline();
	string s = v.read_string();
	string s = v.read_string();
	v.read_string("ACCEPTED"); // only succeeds when it reads the given string.
	v.read_string(4, 5);     // only succeeds when it reads a string with length in inclusive range.
	v.read_long_long();      // reads a long long.
	v.read_long_long(0, 10); // reads integer in inclusive range.
	bool b = v.peek('x');    // test the next character.
	v.WA("The input is not valid."); // Print error and exit with code 43.

	// In its destructor, v automatically exits with code 42 here.
}
