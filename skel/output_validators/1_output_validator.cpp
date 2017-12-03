#include <fstream>
#include <iostream>
using namespace std;

// called as:
// 1_output_validator input answer feedbackdir < output

// Write feedback on wrong solutions to stdout,
// and write internal errors/debug information do stderr.

const int AC = 42, WA = 43;

int main(int arcg, const char *args[]) {
	// Set up the input, answer, and output streams.
	std::ifstream in(args[1]);
	std::ifstream ans(args[2]);
	std::istream &out = cin;

	// Process the data here.

	int answer;
	ans >> answer;

	int output;
	out >> output;

	if(output == answer)
		return AC;
	else {
		std::cout << "Contestant output of " << output << " does not equal expected answer "
		          << answer << std::endl;
		return WA;
	}
}
