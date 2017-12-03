#pragma once
#include <algorithm>
#include <iostream>
using namespace std;

const bool case_sensitive = false;

const int ret_AC = 42, ret_WA = 43;

[[noreturn]] void WA() { exit(ret_WA); }

template <typename U>
[[noreturn]] void WA(U exp) {
	cout << exp << endl;
	exit(ret_WA);
}

template <typename U, typename V>
[[noreturn]] void WA(U exp, V s) {
	cout << "Expected " << exp << ", found " << s << endl;
	exit(ret_WA);
}

[[noreturn]] void AC() { exit(ret_AC); }

void eof() {
	string s;
	if(!(cin >> s)) return;
	WA("EOF", s);
}

string read_string() {
	string s;
	if(cin >> s) return s;
	WA("string", "nothing");
}

string &lowercase(string &s) {
	if(!case_sensitive) return s;
	transform(s.begin(), s.end(), s.begin(), ::tolower);
	return s;
}

void test_string(string t) {
	string s = read_string();
	if(lowercase(s) != lowercase(t)) WA(t, s);
}

void is_int(const string &s) {
	auto it = s.begin();
	// [0-9-]
	if(!(*it == '-' || ('0' <= *it && *it <= '9')))
		WA("integer with leading digit or minus sign", s);
	++it;
	for(; it != s.end(); ++it)
		if(!('0' <= *it && *it <= '9')) WA("integer", s);
}

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

long long read_long_long(long long low, long long high) {
	auto v = read_long_long();
	if(low <= v && v <= high) return v;
	WA("integer between " + to_string(low) + " and " + to_string(high), to_string(v));
}

bool peek(char c) { return (cin >> ws).peek() == char_traits<char>::to_int_type(c); }
