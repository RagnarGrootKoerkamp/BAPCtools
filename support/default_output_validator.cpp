#include <algorithm>
#include <cassert>
#include <cctype>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <ios>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>
using namespace std;

bool case_sensitive         = false;
bool space_change_sensitive = false;

double float_relative_tolerance = 0;
double float_absolute_tolerance = 0;
double float_tolerance          = 0;

string strip_newline(string s) {
	if(not s.empty() and s.back() == '\n') s.pop_back();
	return s;
}

string crop_output(string output) {
	if(output.size() > 200) {
		output.resize(200);
		output += " ...";
	}
	return output;
}

string quick_diff(const string& out, const string& ans) {
	if(count(begin(ans), end(ans), '\n') <= 1 and count(begin(out), end(out), '\n') <= 1)
		return crop_output("Got " + strip_newline(out) + " wanted " + strip_newline(ans));
	return {};
}

pair<bool, string> default_output_validator(const string& ans_path, const string& feedback_dir) {
	// Read answer.
	string ans = [&] {
		stringstream ans_stream;
		ifstream f(ans_path);
		ans_stream << f.rdbuf();
		return ans_stream.str();
	}();

	// Read stdin.
	string out = [] {
		stringstream out_stream;
		cin >> noskipws;
		out_stream << cin.rdbuf();
		return out_stream.str();
	}();

	if(out == ans) return {true, ""};

	// Make lower case if needed.
	if(not case_sensitive) {
		for(auto& c : ans) c = tolower(c);
		for(auto& c : out) c = tolower(c);
		if(out == ans) return {true, "case"};
	}

	const auto& floatabs = float_absolute_tolerance;
	const auto& floatrel = float_relative_tolerance;

	if(space_change_sensitive and floatabs == 0 and floatrel == 0)
		return {false, quick_diff(out, ans)};

	// Split into tokens, depending on space_change_sensitive.
	auto words = [](const string& st) {
		stringstream s(st);
		vector<string> words;
		string w;
		if(space_change_sensitive) {
			s >> noskipws;
			while(!s.eof()) {
				if(s >> w) {
					words.push_back(w);
				} else {
					s.clear();
					assert(s.fail());
					char c;
					if(s >> c) {
						assert(isspace(c));
						words.emplace_back(1, c);
					}
				}
			}
		} else {
			while(s >> w) words.push_back(w);
		}
		return words;
	};
	const auto ans_words = words(ans);
	const auto out_words = words(out);

	if(ans_words == out_words) {
		assert(not space_change_sensitive);
		return {true, "white space"};
	}

	if(floatabs == 0 and floatrel == 0) return {false, quick_diff(out, ans)};

	if(out_words.size() != ans_words.size()) { return {false, quick_diff(out, ans)}; }

	long double max_abs_err = 0;
	long double max_rel_err = 0;
	for(int i = 0; i < out_words.size(); ++i) {
		const auto& w1 = ans_words[i];
		const auto& w2 = out_words[i];
		if(w1 != w2) {
			size_t p1 = 0, p2 = 0;
			// If the answer term doesn't parse as a float, don't try the output term.
			// In this case, we always need equality of w1 and w2.
			long double v1, v2;
			try {
				v1 = stold(w1, &p1);
			} catch(exception& e) { return {false, quick_diff(w2, w1)}; }
			if(p1 < w1.size()) return {false, quick_diff(w2, w1)};

			// If the output term doesn't parse as a float -> WA.
			try {
				v2 = stold(w2, &p2);
			} catch(exception& e) { return {false, quick_diff(out, ans)}; }
			if(p2 < w2.size()) return {false, quick_diff(w2, w1)};

			// If both parse as float -> compare the absolute and relative differences.
			auto abserr = abs(v1 - v2);
			auto relerr = v2 != 0 ? abs(v1 - v2) / v1 : 1000;
			max_abs_err = max(max_abs_err, abserr);
			max_rel_err = max(max_rel_err, relerr);

			if(isnan(v1) != isnan(v2) or isinf(v1) != isinf(v2) or (abserr > float_absolute_tolerance and relerr > float_relative_tolerance))
				return {false, quick_diff(w2, w1)};
		}
	}

	stringstream message;
	message << setprecision(2);
	message << "float: abs " << max_abs_err << " rel " << max_rel_err;
	return {true, message.str()};
}

int main(int argc, char** argv) {
	// string in_path      = argv[1];
	string ans_path     = argv[2];
	string feedback_dir = argv[3];

	for(int i = 4; i < argc; ++i) {
		if(argv[i] == string("case_sensitive")) case_sensitive = true;
		if(argv[i] == string("space_change_sensitive")) space_change_sensitive = true;
		if(argv[i] == string("float_tolerance")) {
			assert(i + 1 < argc);
			float_tolerance = stod(argv[i + 1]);
		}
		if(argv[i] == string("float_absolute_tolerance")) {
			assert(i + 1 < argc);
			float_absolute_tolerance = stod(argv[i + 1]);
		}
		if(argv[i] == string("float_relative_tolerance")) {
			assert(i + 1 < argc);
			float_relative_tolerance = stod(argv[i + 1]);
		}
	}

	if(float_tolerance != 0) {
		assert(float_relative_tolerance == 0);
		assert(float_absolute_tolerance == 0);
		float_relative_tolerance = float_tolerance;
		float_absolute_tolerance = float_tolerance;
	}

	auto res      = default_output_validator(ans_path, feedback_dir);
	auto& ok      = res.first;
	auto& message = res.second;
	cerr << message << "\n";
	if(not ok) return 43;
	return 42;
}
