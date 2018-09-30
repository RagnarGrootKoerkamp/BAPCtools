#include "validation.h"

// For FIXED OUTPUT PROBLEMS:
// This program will be called as
// output_validator input < ans
//
// You should verify the grammar of the answer file.
// See input_validator.cpp for information on how to use the Validator class.
// Furthermore you should check simple properties of the answer.

// For DYNAMIC OUTPUT PROBLEMS:
// This program will be called as
// output_validator input answer < team_output
//
// Please check the grammar of the team output using the Validator class.
// See input_validator.cpp for information on how to use the Validator class.
// You should also check the validity of the answer here.
// For example, check that a tree printed by the team is a tree indeed.

// TODO: Remove these comments, and summarize your output validator.

int main(int argc, char **argv) {
	// Set up the input and answer streams.
	std::ifstream in(argv[1]);
	// std::ifstream ans(argv[2]); // Only for custom checker.
	OutputValidator v(argc, argv);

	int input;
	in >> input;
	int answer = v.read_long_long(input, input);
	v.newline();
}
