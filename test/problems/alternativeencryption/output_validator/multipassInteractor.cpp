#include "validate.h"

inline const std::regex ACTION("encrypt|decrypt", REGEX_OPTIONS);
inline const std::regex CHARS("[a-z]*", REGEX_OPTIONS);

int main(int argc, char **argv) {
	OutputValidator::init(argc, argv);
	Multipass::init();
	using namespace OutputValidator;
	using namespace Multipass;

	if (!caseSensitive) juryErr << "call with: case_sensitive " << FAIL;

	std::string action = testIn.string(ACTION);
	if (pass == 0 && action != "encrypt") juryErr << "action: "<< action << ", in pass: " << pass << FAIL;
	if (pass == 1 && action != "decrypt") juryErr << "action: "<< action << ", in pass: " << pass << FAIL;
	if (pass < 0 || pass > 1) juryErr << "pass: " << pass << FAIL;

	Integer n = testIn.integer();

	if (action == "decrypt") {
		for (Integer i = 0; i < n; i++) {
			std::string expected = prevstate.string();
			teamAns.expectString(expected);
			teamAns.newline();
		}
		teamAns.eof();
		juryOut << "OK" << AC;
	} else {
		nextpass << "decrypt" << std::endl;
		nextpass << n << std::endl;
		for (Integer i = 0; i < n; i++) {
			std::string in = testIn.string();
			std::string ans = teamAns.string(CHARS, in.size(), in.size() + 1);
			for (std::size_t j = 0; j < in.size(); j++) {
				if (in[j] == ans[j]) juryOut << "Char: " << in[j] << " not encrypt at pos: " << j << ", in testcase: " << i << WA;
			}
			nextpass << ans << std::endl;
			nextstate << in << std::endl;
		}
		NEXT();
	}
}
