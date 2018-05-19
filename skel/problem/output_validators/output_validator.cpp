#include "validation.h"

// Check the correctness of the answer here.
// Your program must return 42 when the input is correct.
// When there is something wrong with the input, return 43.
// In this case, it is also a good idea to print some useful debug information to stdout.

// When your program crashes unexpectedly, or something weird is going on,
// please write some info to stderr and return anything different from 42 and 43.

// For default output validation, where the team output is directly compared to the .ans,
// this script is called as:
//		output_validator input answer feedbackdir < answer
//
// Please validate:
//	- the syntax/grammer of the answer file.
//	- optionally, the correctness of the answer.

// For custom output validation, this is called as:
//		output_validator input answer feedbackdir < team_output
//
// Please validate:
//	- The syntax/grammar of the team output.
//	- The correctness of the team output.

int main(int argc, char **argv) {
	// Set up the input and answer streams.
	std::ifstream in(args[1]);
	std::ifstream ans_stream(args[2]);
	Validator ans(argc, argv, ans_stream);

	int input;
	in >> input;
	int answer = v.read_long_long(input, input);
	v.newline();

	// In its destructor, v automatically exits with code 42 here.
	return;

	// Other useful commands:
	v.space();
	v.newline();
	v.read_string();
	v.test_string("ACCEPTED");        // only succeeds when it reads the given string.
	int a  = v.read_long_long();      // reads a long long.
	int b  = v.read_long_long(0, 10); // reads integer in inclusive range.
	char p = 'x';
	bool b = v.peek(p);              // test the next character.
	v.WA("The input is not valid."); // Return error code 43.
}
