#include <algorithm>
#include <cassert>
#include <cctype>
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
	// read answer
	stringstream ans_stream;
	{
		ifstream f(ans_path);
		ans_stream << f.rdbuf();
	}
	string ans = ans_stream.str();

	stringstream out_stream;
	cin >> noskipws;
	out_stream << cin.rdbuf();
	string out = out_stream.str();

	if(out == ans) return {true, ""};

	if(not case_sensitive) {
		for(auto& c : ans) c = tolower(c);
		for(auto& c : out) c = tolower(c);
		if(out == ans) return {true, "case"};
	}

	const auto& floatabs = float_absolute_tolerance;
	const auto& floatrel = float_relative_tolerance;

	if(space_change_sensitive and floatabs == 0 and floatrel == 0)
		return {false, quick_diff(out, ans)};

	vector<string> ans_words, out_words;
	auto words = [](stringstream& s) {
		vector<string> words;
		string w;
		if(space_change_sensitive) {
			s >> noskipws;
			while(!s.eof()) {
				if(s >> w) {
					words.push_back(w);
				} else {
					s.clear();
					assert(s.failbit);
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
	ans_words = words(ans_stream);
	out_words = words(out_stream);

	if(ans_words == out_words) {
		assert(not space_change_sensitive);
		return {true, "white space"};
	}

	if(out_words.size() != ans_words.size()) { return {false, quick_diff(out, ans)}; }

	long double max_abs_err = 0;
	long double max_rel_err = 0;
	for(int i = 0; i < out_words.size(); ++i) {
		const auto& w1 = out_words[i];
		const auto& w2 = ans_words[i];
		if(w1 != w2) {
			size_t p1 = 0, p2 = 0;
			long double v1 = stold(w1, &p1);
			long double v2 = stold(w2, &p2);
			if(p1 < w1.size() or p2 < w2.size()) return {false, quick_diff(out, ans)};
			auto abserr = abs(v1 - v2);
			auto relerr = v2 != 0 ? abs(v1 - v2) / v2 : 1000;
			max_abs_err = max(max_abs_err, abserr);
			max_rel_err = max(max_rel_err, relerr);

			if(abserr > float_absolute_tolerance and relerr > float_relative_tolerance)
				return {false, quick_diff(out, ans)};
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
		if(argv[i] == "case_sensitive"s) case_sensitive = true;
		if(argv[i] == "space_change_sensitive"s) space_change_sensitive = true;
		if(argv[i] == "float_tolerance"s) {
			assert(i + 1 < argc);
			float_tolerance = stod(argv[i + 1]);
		}
		if(argv[i] == "float_absolute_tolerance"s) {
			assert(i + 1 < argc);
			float_absolute_tolerance = stod(argv[i + 1]);
		}
		if(argv[i] == "float_relative_tolerance"s) {
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

	auto [ok, message] = default_output_validator(ans_path, feedback_dir);
	cerr << message << "\n";
	if(not ok) return 43;
	return 42;
}
