// A header library to safely parse team input.
// It does not support floating points or big integers.
// Author: Ragnar Groot Koerkamp

// The easiest way to use this is to symlink it from a validator directory,
// so that it will be picked up when creating a contest zip.

// The default checking behaviour is lenient for both white space and case.
// When validating .in and .ans files, the case_sensitve and space_change_sensitive flags should be
// passed. When validating team output, the flags in problem.yaml should be used.

#include <algorithm>
#include <stdexcept>
#include <fstream>
#include <iostream>
#include <limits>
using namespace std;

const string case_sensitive_flag = "case_sensitive";
const string ws_sensitive_flag = "space_change_sensitive";

class Validator {
  protected:
	Validator(bool ws, bool case_ , istream &in) : in(in), ws(ws), case_sensitive(case_) {
		if(ws) in >> noskipws;
		else in >> skipws;
	}

  public:
	// No copying, no moving.
	Validator(const Validator &) = delete;
	Validator(Validator &&)      = delete;

	// At the end of the scope, check whether the EOF has been reached.
	// If so, return AC. Otherwise, return WA.
	~Validator() {
		eof();
		AC();
	}

	void space() {
		if(ws) {
			char c;
			in >> c;
			if(c != ' ') expected("space", string("\"") + c + "\"");
		}
	}

	void newline() {
		if(ws) {
			char c;
			in >> c;
			if(c != '\n') expected("newline", string("\"") + c + "\"");
		}
	}

	// Just read a string.
	string read_string() { return read_string_impl(); }

	// Read a string and make sure it equals `expected`.
	string read_string(string expected) { return read_string_impl(expected); }

	// Read an arbitrary string of a given length.
	string read_string(size_t min, size_t max) {
		string s = read_string();
		if(s.size() < min || s.size() > max)
			expected("String of length between " + to_string(min) + " and " + to_string(max), s);
		return s;
	}

	// Read the string t.
	void test_string(string t) {
		string s = read_string();
		if(case_sensitive) {
			if(s != t) expected(t, s);
		} else {
			if(lowercase(s) != lowercase(t)) expected(t, s);
		}
	}

	// Read a long long.
	long long read_long_long() {
		string s = read_string_impl("", "integer");
		if(s.empty()){
			WA("Want integer, found nothing");
		}
		long long v;
		try {
			size_t chars_processed = 0;
			v                      = stoll(s, &chars_processed);
			if(chars_processed != s.size())
				WA("Parsing " + s + " as long long failed! Did not process all characters");
		} catch(const out_of_range &e) {
			WA("Number " + s + " does not fit in a long long!");
		} catch(const invalid_argument &e) { WA("Parsing " + s + " as long long failed!"); }
		// Check for leading zero.
		if(v == 0){
			if(s.size() != 1)
				WA("Parsed 0, but has leading 0 or minus sign: " , s);
		}
		if(v > 0){
			if(s[0] == '0')
				WA("Parsed ",v,", but has leading 0: " , s);
		}
		if(v < 0){
			if(s.size() <= 1)
				WA("Parsed ",v,", but string is: " , s);
			if(s[1] == '0')
				WA("Parsed ",v,", but has leading 0: " , s);
		}
		return v;
	}

	// Read a long long within a given range.
	long long read_long_long(long long low, long long high) {
		auto v = read_long_long();
		if(low <= v && v <= high) return v;
		expected("integer between " + to_string(low) + " and " + to_string(high), to_string(v));
	}

	int read_int() {
		return read_long_long(std::numeric_limits<int>::min(), std::numeric_limits<int>::max());
	}

	int read_int(int low, int high) {
		int v = read_long_long(std::numeric_limits<int>::min(), std::numeric_limits<int>::max());
		if(low <= v && v <= high) return v;
		expected("integer between " + to_string(low) + " and " + to_string(high), to_string(v));
	}

	// Read a long double.
	long double read_long_double() {
		string s = read_string_impl("", "long double");
		long double v;
		try {
			size_t chars_processed;
			v = stold(s, &chars_processed);
			if(chars_processed != s.size())
				WA("Parsing ", s, " as long double failed! Did not process all characters.");
		} catch(const out_of_range &e) {
			WA("Number " + s + " does not fit in a long double!");
		} catch(const invalid_argument &e) { WA("Parsing " + s + " as long double failed!"); }
		return v;
	}

	// Check the next character.
	bool peek(char c) {
		if(!ws) in >> ::ws;
		return in.peek() == char_traits<char>::to_int_type(c);
	}

	// Return WRONG ANSWER verdict.
	[[noreturn]] void expected(string exp = "", string s = "") {
		if(s.size())
			WA("Expected ", exp, ", found ", s);
		else
			WA(exp);
	}

  private:
	template <typename T>
	[[noreturn]] void WA_impl(T t) {
		cerr << t << endl;
		exit(ret_WA);
	}

	template <typename T, typename... Ts>
	[[noreturn]] void WA_impl(T t, Ts... ts) {
		cerr << t;
		WA_impl(ts...);
	}

  public:
	template <typename... Ts>
	[[noreturn]] void WA(Ts... ts) {
		auto pos = get_file_pos();
		cerr << pos.first << ":" << pos.second << ": ";
		WA_impl(ts...);
	}

	template <typename... Ts>
	void assert(bool b, Ts... ts) {
		if(!b) WA(ts...);
	}

  private:
	// Read an arbitrary string.
	// expected: if not "", string must equal this.
	// wanted: on failure, print "expected <wanted>, got ..."
	string read_string_impl(string expected_string = "", string wanted = "string") {
		if(ws) {
			char next = in.peek();
			if(isspace(next)) expected(wanted, next=='\n' ? "newline" : "whitespace");
		}
		string s;
		if(in >> s) {
			if(!case_sensitive) {
				s               = lowercase(s);
				expected_string = lowercase(expected_string);
			}
			if(!expected_string.empty() && s != expected_string)
				WA("Expected string \"", expected_string, "\", but found ", s);
			return s;
		}
		expected(wanted, "nothing");
	}

	// Return ACCEPTED verdict.
	[[noreturn]] void AC() { exit(ret_AC); }

	void eof() {
		if(in.eof()) return;
		// Sometimes EOF hasn't been triggered yet.
		if(!ws) in >> ::ws;
		char c = in.get();
		if(c == char_traits<char>::eof()) return;
		string got = string("\"") + char(c) + '"';
		if(c=='\n') got="newline";
		expected("EOF", got);
	}

	// Convert a string to lowercase is matching is not case sensitive.
	string &lowercase(string &s) {
		if(!case_sensitive) return s;
		transform(s.begin(), s.end(), s.begin(), ::tolower);
		return s;
	}

	std::pair<int,int> get_file_pos() {
		int line = 1, col = 0;
		in.clear();
		auto originalPos = in.tellg();
		if (originalPos < 0) 
			return {-1, -1};
		in.seekg(0);
		char c;
		while ((in.tellg() < originalPos) && in.get(c))
		{
			if (c == '\n') ++line, col=0;
			else ++col;
		}
		return {line, col};
	}

	const int ret_AC = 42, ret_WA = 43;
	istream &in;
	bool ws;
	bool case_sensitive;

};

class InputValidator : public Validator {
  public:
	// An InputValidator is always both whitespace and case sensitive.
	InputValidator() : Validator(true, true, std::cin) {}
};

class OutputValidator : public Validator {
  public:
	// An OutputValidator can be run in different modes.
	OutputValidator(int argc, char **argv, istream &in = std::cin) :
		Validator(is_ws_sensitive(argc, argv), is_case_sensitive(argc, argv), in) {
	}

  private:
	static bool is_ws_sensitive(int argc, char **argv){
		for(int i = 0; i < argc; ++i) {
			if(argv[i] == ws_sensitive_flag) return true;
		}
		return false;
	}
	static bool is_case_sensitive(int argc, char **argv){
		for(int i = 0; i < argc; ++i) {
			if(argv[i] == case_sensitive_flag) return true;
		}
		return false;
	}
};
