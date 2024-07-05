#include <algorithm>
#include <cassert>
#include <cctype>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <ios>
#include <iostream>
#include <limits>
#include <optional>
#include <sstream>
#include <string>
#include <vector>

//============================================================================//
// Constants                                                                  //
//============================================================================//
constexpr int AC = 42;
constexpr int WA = 43;

constexpr std::string_view CASE_SENSITIVE           = "case_sensitive";
constexpr std::string_view SPACE_CHANGE_SENSITIVE   = "space_change_sensitive";
constexpr std::string_view FLOAT_ABSOLUTE_TOLERANCE = "float_absolute_tolerance";
constexpr std::string_view FLOAT_RELATIVE_TOLERANCE = "float_relative_tolerance";
constexpr std::string_view FLOAT_TOLERANCE          = "float_tolerance";
constexpr std::string_view TEXT_ELLIPSIS            = "[...]";
constexpr std::string_view WHITESPACE               = " \f\n\r\t\v";

//============================================================================//
// parameters                                                                 //
//============================================================================//
bool case_sensitive         = false;
bool space_change_sensitive = false;
bool compare_floats         = false;

long double float_relative_tolerance = -1;
long double float_absolute_tolerance = -1;

//============================================================================//
// Utility                                                                    //
//============================================================================//
namespace util {
	constexpr bool is_space(char c) {
		return WHITESPACE.find(c) != std::string_view::npos;
	}

	constexpr bool is_digits(std::string_view token) {
		for (char c : token) {
			if (c < '0' or c > '9') return false;
		}
		return true;
	}

	constexpr bool is_integer(std::string_view token) {
		if (token.substr(0, 1) == "-") token.remove_prefix(1);  // ignore optional - sign
		if (token.empty()) return false;                        // integers need at least one digit
		if (token.size() > 1 and token[0] == '0') return false; // integers do not start with 0 (unless they are exactly "0")
		if (not is_digits(token)) return false;                 // integers are just digits
		return true;
	}

	constexpr bool is_decimal(std::string_view token) {
		std::size_t dot = token.find('.');
		if (not is_integer(token.substr(0, dot))) return false;                        // decimals before the dot are *non empty* integers
		if (dot < token.size() and not is_digits(token.substr(dot + 1))) return false; // decimals only have digits after the dot
		return true;
	}

	constexpr bool is_float(std::string_view token) {
		std::size_t e = token.find_first_of("eE");
		if (not is_decimal(token.substr(0, e))) return false; // float is a decimal
		if (e < token.size()) {                               // followed by an optional e[-+]?<digits>
			bool has_sign = token[e + 1] == '-' || token[e + 1] == '+';
			auto digits = token.substr(e + 1 + has_sign);
			if (digits == "" or not is_digits(digits)) return false;
		}
		return true;
	}
}

//============================================================================//
// IO                                                                         //
//============================================================================//
std::string read_raw(std::istream& in) {
	std::stringstream raw;
	assert(in.good());
	raw << in.rdbuf();
	return raw.str();
}

// each token is either EOF, a single whitespace charachter or a string without any whitespace character
struct token_view {
	std::string_view token;

	token_view() {}
	token_view(std::string_view token) : token{token} {}

	bool is_eof() const {
		return token.empty();
	}

	std::optional<char> is_space() const {
		if (token.size() != 1) return {};
		if (not util::is_space(token[0])) return {};
		return token[0];
	}

	std::optional<long double> is_float() const {
		if (not util::is_float(token)) return {};
		try {
			//std::from_chars for floats is not widely supported ):
			std::size_t pos = 0;
			std::string tmp(token);
			long double res = std::stold(tmp, &pos);
			assert(pos == token.size());
			assert(std::isfinite(res));
			return res;
		} catch(const std::out_of_range& /**/) {
			// i dont know how to handle this... return +-inf?
			return {};
		} catch(...) {}
		// this should not happen. Except for the range check our parsing is stricter than std::stold
		assert(false);
		return {};
	}

	std::string formatted(std::size_t lim = 200) const {
		assert(lim >= TEXT_ELLIPSIS.size());
		if (is_eof()) return "EOF";
		if (token == " ") return "\" \"";
		if (token == "\f") return "\"\\f\"";
		if (token == "\n") return "\"\\n\"";
		if (token == "\r") return "\"\\r\"";
		if (token == "\t") return "\"\\t\"";
		if (token == "\v") return "\"\\v\"";
		std::string res(token);
		if (res.size() > lim) {
			res.resize(lim - TEXT_ELLIPSIS.size());
			res += TEXT_ELLIPSIS;
		}
		return res;
	}

	bool equal(token_view o) const {
		return token == o.token;
	}

	bool case_insensitive_equal(token_view o) const {
		if (token.size() != o.token.size()) return false;
		for (std::size_t i = 0; i < token.size(); i++) {
			int a = std::tolower(static_cast<unsigned char>(token[i]));
			int b = std::tolower(static_cast<unsigned char>(o.token[i]));
			if (a != b) return false;
		}
		return true;
	}
};

struct token_stream {
	std::string raw;
	std::string_view todo;
	token_view last;

	token_stream() {}

	token_stream(token_stream&& other) = delete;
	token_stream& operator=(token_stream&& other) = delete;
	token_stream(const token_stream&) = delete;
	token_stream& operator=(const token_stream&) = delete;

	void set(std::string_view s) {
		raw = s;
		todo = raw;
		next();
	}

	void next() {
		std::size_t end = todo.size();
		if (not todo.empty()) {
			end = std::clamp<std::size_t>(todo.find_first_of(WHITESPACE), 1, end);
		}
		last = token_view(todo.substr(0, end));
		todo.remove_prefix(end);
	}

	const token_view& operator*() const {
		return last;
	}

	const token_view* operator->() const {
		return &last;
	}
};

//============================================================================//
// Diff                                                                       //
//============================================================================//
struct diff {
	std::string message;
	std::optional<std::string> case_change;
	std::optional<std::string> space_change;
	int verdict;

	diff() : message{}, case_change{}, space_change{}, verdict{AC} {}

	diff& set_diff(const std::string& expected, const std::string& given) {
		message = "Got: " + given + ", wanted: " + expected;
		verdict = WA;
		return *this;
	}

	diff& set_case_change(const std::string& expected, const std::string& given) {
		if (not case_change) {
			case_change = "Case error. Got: " + given + ", wanted: " + expected;
			if (case_sensitive) verdict = WA;
		}
		return *this;
	}

	diff& set_space_change(const std::string& expected, const std::string& given) {
		if (not space_change) {
			space_change = "Whitespace error. Got: " + given + ", wanted: " + expected;
			if (space_change_sensitive) verdict = WA;
		}
		return *this;
	}

	friend std::ostream& operator<<(std::ostream& os, const diff& d) {
		if (not d.message.empty()) os << d.message << "\n";
		if (d.case_change and case_sensitive) os << *(d.case_change) << "\n";
		if (d.space_change and space_change_sensitive) os << *(d.space_change) << "\n";
		if (d.case_change and not case_sensitive) os << *(d.case_change) << " (Ignored)\n";
		if (d.space_change and not space_change_sensitive) os << *(d.space_change) << " (Ignored)\n";
		return os << std::flush;
	}
};

diff check(const std::filesystem::path& ans_path) {
	// read input
	token_stream jury, team;
	{
		std::ifstream tmp(ans_path);
		jury.set(read_raw(tmp));
	}
	team.set(read_raw(std::cin));

	// handle tokenized streams
	diff res;
	while (not jury->is_eof() and not team->is_eof()) {
		if (jury->equal(*team)) {
			// identical input is always ok
			jury.next();
			team.next();
		} else if (jury->is_space() or team->is_space()) {
			// team and,or jury have space (but are not equal)
			res.set_space_change(jury->formatted(), team->formatted());
			if (jury->is_space()) jury.next();
			if (team->is_space()) team.next();
			// try to continue and find a non space change error
			// if (space_change_sensitive) return res;
		} else if (compare_floats and jury->is_float() and team->is_float()) {
			// team and jury have finite floats
			long double expected = jury->is_float().value();
			long double given = team->is_float().value();

			std::string diff = "";
			bool equal = false;
			if (float_absolute_tolerance >= 0) {
				long double abs = std::abs(given-expected);
				diff += "Absolute difference: " + std::to_string(abs);
				if (abs <= float_absolute_tolerance) {
					equal = true;
				}
			}
			if (float_relative_tolerance >= 0) {
				long double rel = std::abs((given-expected)/expected);
				if (diff != "") diff += ", ";
				diff += "Relative difference: " + std::to_string(rel);
				if (rel <= float_relative_tolerance) {
					equal = true;
				}
			}
			if (not equal) {
				res.set_diff(jury->formatted(), team->formatted());
				res.message += " (" + diff + ")";
				return res;
			}
			jury.next();
			team.next();
		} else if (jury->case_insensitive_equal(*team)) {
			// tokens are "equal" but some characters have a different case
			// ignore this if the token is actually a float
			res.set_case_change(jury->formatted(), team->formatted());
			jury.next();
			team.next();
			// try to continue and find a non case change error
			// if (case_sensitive) return res;
		} else{
			return res.set_diff(jury->formatted(), team->formatted());
		}
	}
	while (not team->is_eof()) {
		// team has more output
		if (not team->is_space()) {
			res.message = "Team has trailing output: " + team->formatted();
			res.verdict = WA;
			return res;
		}
		res.set_space_change(jury->formatted(), team->formatted());
		team.next();
		// try to continue and find a non space change error
		// if (space_change_sensitive) return res;
	}
	while (not jury->is_eof()) {
		// jury has more output
		if (not jury->is_space()) {
			res.message = "Team is missing output (jury had: " + jury->formatted() + ")";
			res.verdict = WA;
			return res;
		}
		res.set_space_change(jury->formatted(), team->formatted());
		jury.next();
		// try to continue and find a non space change error
		// if (space_change_sensitive) return res;
	}

	if (res.verdict == AC) {
		res.message = "ok";
	}
	return res;
}

int main(int argc, char** argv) {
	//std::filesystem::path in_path(argv[1]);
	std::filesystem::path ans_path(argv[2]);
	//std::filesystem::path feedback_dir(argv[3]);


	// read parameters:
	// - case_sensitive
	// - space_change_sensitive
	// - float_absolute_tolerance
	// - float_relative_tolerance
	// - float_tolerance
	long double float_tolerance = -1;
	for (int i = 4; i < argc; i++) {
		if (argv[i] == CASE_SENSITIVE) case_sensitive = true;
		if (argv[i] == SPACE_CHANGE_SENSITIVE) space_change_sensitive = true;
		if (argv[i] == FLOAT_TOLERANCE) {
			assert(float_tolerance < 0);
			assert(i + 1 < argc);
			float_tolerance = std::stold(argv[i + 1]);
			assert(float_tolerance >= 0);
		}
		if (argv[i] == FLOAT_ABSOLUTE_TOLERANCE) {
			assert(float_absolute_tolerance < 0);
			assert(i + 1 < argc);
			float_absolute_tolerance = std::stold(argv[i + 1]);
			assert(float_absolute_tolerance >= 0);
		}
		if (argv[i] == FLOAT_RELATIVE_TOLERANCE) {
			assert(float_relative_tolerance < 0);
			assert(i + 1 < argc);
			float_relative_tolerance = std::stold(argv[i + 1]);
			assert(float_relative_tolerance >= 0);
		}
	}

	// set float tolerance
	if (float_tolerance >= 0) {
		assert(float_relative_tolerance < 0);
		assert(float_absolute_tolerance < 0);
		float_relative_tolerance = float_tolerance;
		float_absolute_tolerance = float_tolerance;
	}
	compare_floats = float_relative_tolerance >= 0 or float_absolute_tolerance >= 0;

	// compare jury and submission
	diff res = check(ans_path);
	std::cerr << res;
	return res.verdict;
}
