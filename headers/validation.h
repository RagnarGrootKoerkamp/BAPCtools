// A header library to safely parse team input.
// It does not support floating points or big integers.

// The easiest way to use this is to symlink it from a validator directory,
// so that it will be picked up when creating a contest zip.

#include <algorithm>
#include <iostream>
using namespace std;

class Validator {
	const int ret_AC = 42, ret_WA = 43;
	const bool case_sensitive;

  public:
	Validator(bool case_sensitive = false) : case_sensitive(case_sensitive) {}

	// At the end of the scope, check whether the EOF has been reached.
	// If so, return AC. Otherwise, return WA.
	~Validator() {
		eof();
		AC();
	}

	// Read an arbitrary string.
	string read_string() {
		string s;
		if(cin >> s) return s;
		WA("string", "nothing");
	}

	// Read the string t.
	void test_string(string t) {
		string s = read_string();
		if(lowercase(s) != lowercase(t)) WA(t, s);
	}

	// Check whether a string is an integer.
	void is_int(const string &s) {
		auto it = s.begin();
		// [0-9-]
		if(!(*it == '-' || ('0' <= *it && *it <= '9')))
			WA("integer with leading digit or minus sign", s);
		++it;
		for(; it != s.end(); ++it)
			if(!('0' <= *it && *it <= '9')) WA("integer", s);
	}

	// Read a long long.
	long long read_long_long() {
		string s;
		if(!(cin >> s)) WA("integer", "nothing");
		is_int(s);
		long long val;
		try {
			val = stoll(s);
		} catch(const out_of_range &e) {
			WA("Number " + s + " does not fit in a long long!");
		} catch(const invalid_argument &e) { WA("Parsing " + s + " as long long failed!"); }
		return val;
	}

	// Read a long long within a given range.
	long long read_long_long(long long low, long long high) {
		auto v = read_long_long();
		if(low <= v && v <= high) return v;
		WA("integer between " + to_string(low) + " and " + to_string(high), to_string(v));
	}

	// Check the next non-whitespace character.
	bool peek(char c) { return (cin >> ws).peek() == char_traits<char>::to_int_type(c); }

  private:
	// Return WRONG ANSWER verdict.
	[[noreturn]] void WA(string exp = "", string s = "") {
		if(s.size())
			cout << "Expected " << exp << ", found " << s << endl;
		else if(exp.size())
			cout << exp << endl;
		exit(ret_WA);
	}

	// Return ACCEPTED verdict.
	[[noreturn]] void AC() { exit(ret_AC); }

	// Check whether the End Of File has been reached.
	void eof() {
		string s;
		if(!(cin >> s)) return;
		WA("EOF", s);
	}

	// Convert a string to lowercase is matching is not case sensitive.
	string &lowercase(string &s) {
		if(!case_sensitive) return s;
		transform(s.begin(), s.end(), s.begin(), ::tolower);
		return s;
	}
};
