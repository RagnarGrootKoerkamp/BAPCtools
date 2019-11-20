// A header library to safely parse team input.
// It does not support floating points or big integers.
// Author: Ragnar Groot Koerkamp

// The easiest way to use this is to symlink it from a validator directory,
// so that it will be picked up when creating a contest zip.

// The default checking behaviour is lenient for both white space and case.
// When validating .in and .ans files, the case_sensitive and space_change_sensitive flags should be
// passed. When validating team output, the flags in problem.yaml should be used.

// Compile with -Duse_source_location to enable std::experimental::source_location.
// This is needed for constraints checking.

#include <algorithm>
#include <cassert>
#include <stdexcept>
#include <fstream>
#include <iostream>
#include <iomanip>
#include <limits>
#include <map>
#include <vector>
#include <type_traits>
#include <random>
#include <string>

#ifdef use_source_location
#include <experimental/source_location>
using std::experimental::source_location;
#else
struct source_location {
	static source_location current(){ return {}; }
	int line(){ return 0; }
	std::string file_name(){ return ""; }
};
#endif

using namespace std;

const string case_sensitive_flag = "case_sensitive";
const string ws_sensitive_flag = "space_change_sensitive";
const string constraints_file_flag = "--constraints_file";
const string generate_flag = "--generate";

class Validator {
  protected:
	Validator(bool ws_, bool case_ , istream &in_, string constraints_file_path_ = "", bool gen_ = false)
	   	: in(in_), ws(ws_), case_sensitive(case_), constraints_file_path(constraints_file_path_), gen(gen_) {
		if(gen) return;
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
		write_constraints();
		AC();
	}

	void space() {
		if(gen){
			out << ' ';
			return;
		}

		if(ws) {
			char c;
			in >> c;
			check(!in.eof(), "Expected space, found EOF.");
			if(c != ' ') expected("space", string("\"") + ((c=='\n' or c=='\r') ? string("newline"):string(1, c)) + "\"");
		}
	}

	void newline() {
		if(gen){
			out << '\n';
			return;
		}
		if(ws) {
			char c;
			in >> c;
			check(!in.eof(), "Expected newline, found EOF.");
			if(c != '\n'){
				if(c == '\r') expected("newline", "DOS line ending (\\r)");
				else expected("newline", string("\"") + c + "\"");
			}
		}
	}

	// Just read a string.
	string read_string() {
		assert(!gen && "Generating strings is not supported!");
	   	return read_string_impl();
   	}

	// Read a string and make sure it equals `expected`.
	string read_string(string expected) {
		if(gen){
			out << expected;
			return expected;
		}
	   	return read_string_impl(expected);
   	}

	// Read an arbitrary string of a given length.
	string read_string(long long min, long long max, source_location loc = source_location::current()) {
		assert(!gen && "Generating strings is not supported!");
		string s = read_string();
		long long size = s.size();
		if(size < min || size > max)
			expected("String of length between " + to_string(min) + " and " + to_string(max), s);
		log_constraint(min, max, size, loc);
		return s;
	}

	// Read the string t.
	void test_string(string t) {
		if(gen){
			out << t;
			return;
		}
		string s = read_string();
		if(case_sensitive) {
			if(s != t) expected(t, s);
		} else {
			if(lowercase(s) != lowercase(t)) expected(t, s);
		}
	}

	// Read a long long.
	long long read_long_long() {
		if(gen){
			std::uniform_int_distribution<long long> dis(std::numeric_limits<long long>::lowest(), std::numeric_limits<long long>::max());
			auto v = dis(rng);
			out << v;
			return v;
		}
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
	long long read_long_long(long long low, long long high, source_location loc = source_location::current()) {
		if(gen){
			assert(low <= high);
			std::uniform_int_distribution<long long> dis(low, high);
			auto v = dis(rng);
			out << v;
			return v;
		}
		auto v = read_long_long();
		if(v < low or v > high)
			expected("integer between " + to_string(low) + " and " + to_string(high), to_string(v));
		log_constraint(low, high, v, loc);
		return v;
	}

	int read_int() {
		return read_long_long(std::numeric_limits<int>::lowest(), std::numeric_limits<int>::max(), source_location());
	}

	int read_int(int low, int high, source_location loc = source_location::current()) {
		auto v = read_long_long(low, high, loc);
		log_constraint(low, high, v, loc);
		return v;
	}

	// Read a long double.
	long double read_long_double() {
		if(gen){
			std::uniform_real_distribution<long double> dis(std::numeric_limits<long double>::lowest(), std::numeric_limits<long double>::max());
			auto v = dis(rng);
			out << setprecision(10) << fixed << v;
			return v;
		}
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

	long double read_long_double(long double low, long double high, source_location loc = source_location::current()) {
		if(gen){
			assert(low <= high);
			std::uniform_real_distribution<long double> dis(low, high);
			auto v = dis(rng);
			out << setprecision(10) << fixed << v;
			return v;
		}
		long double v = read_long_double();
		if(v < low or v > high)
			expected("long double between " + to_string(low) + " and " + to_string(high), to_string(v));
		log_constraint(low, high, v, loc);
		return v;
	}


	// Check the next character.
	bool peek(char c) {
		if(gen){
			std::bernoulli_distribution dis(0.5);
			return dis(rng);
		}
		if(!ws) in >> ::ws;
		if(case_sensitive)
		   	return in.peek() == char_traits<char>::to_int_type(c);
		else
		   	return tolower(in.peek()) == tolower(char_traits<char>::to_int_type(c));
	}

	// Return WRONG ANSWER verdict.
	[[noreturn]] void expected(string exp = "", string s = "") {
		assert(!gen && "Expected is not supported for generators.");
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
	void check(bool b, Ts... ts) {
		if(!b) WA(ts...);
	}

  private:
	// Read an arbitrary string.
	// expected: if not "", string must equal this.
	// wanted: on failure, print "expected <wanted>, got ..."
	string read_string_impl(string expected_string = "", string wanted = "string") {
		assert(!gen && "read_string_impl is not supported for generators.");
		if(ws) {
			char next = in.peek();
			if(isspace(next)) expected(wanted, next=='\n' ? "newline" : "whitespace");
			if(in.eof()) expected(wanted, "EOF");
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
	[[noreturn]] void AC() {
	   	exit(ret_AC);
   	}

	void eof() {
		if(gen) return;
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
		if(case_sensitive) return s;
		transform(s.begin(), s.end(), s.begin(),
				[](unsigned char c){ return std::tolower(c); }
			   	);
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

	// Keep track of the min/max value read at every call site.
	template<typename T>
	struct Bounds {
		Bounds(T min, T max, T low, T high) : min(min), max(max), low(low), high(high) {}
		T min, max;  // Smallest / largest value observed
		T low, high; // Bounds
		bool has_min=false, has_max=false;
	};
	map<string, Bounds<long long>> int_bounds;
	map<string, Bounds<long double>> float_bounds;
  public:
	void log_constraint(long long low, long long high, long long v, source_location loc = source_location::current()){
		// Do not log when line number is unknown/default/unsupported.
		if(loc.line() == 0 or constraints_file_path.empty()) return;

		string location = string(loc.file_name())+":"+to_string(loc.line());

		auto& done = int_bounds.emplace(location, Bounds<long long>(v, v, low, high)).first->second;
		if(v < done.min){
			done.min = v;
			done.low = low;
		}
		if(v > done.max){
			done.max = v;
			done.high = high;
		}
		done.has_min |= v == low;
		done.has_max |= v == high;
	}
	void log_constraint(long double low, long double high, long double v, source_location loc = source_location::current()){
		cerr << "FALSE\n";
		// Do not log when line number is unknown/default/unsupported.
		if(loc.line() == 0 or constraints_file_path.empty()) return;

		string location = string(loc.file_name())+":"+to_string(loc.line());

		auto& done = float_bounds.emplace(location, Bounds<long double>(v, v, low, high)).first->second;
		if(v < done.min){
			done.min = v;
			done.low = low;
		}
		if(v > done.max){
			done.max = v;
			done.high = high;
		}
		done.has_min |= v == low;
		done.has_max |= v == high;
	}

  private:
	void write_constraints(){
		if(constraints_file_path.empty()) return;

		ofstream out(constraints_file_path);

		for(const auto& d : int_bounds)
			out << d.first << " " << d.second.has_min << " " << d.second.has_max << " " << d.second.min << " " << d.second.max << " " << d.second.low << " " << d.second.high << endl;
		for(const auto& d : float_bounds)
			out << d.first << " " << d.second.has_min << " " << d.second.has_max << " " << d.second.min << " " << d.second.max << " " << d.second.low << " " << d.second.high << endl;
	}

	const int ret_AC = 42, ret_WA = 43;
	istream &in = std::cin;
	ostream &out = std::cout;
	bool ws = true;
	bool case_sensitive = true;
	const string constraints_file_path;
	bool gen = false;

	std::mt19937_64 rng{std::random_device()()};
};

class InputValidator : public Validator {
  public:
	// An InputValidator is always both whitespace and case sensitive.
	InputValidator(int argc=0, char** argv=nullptr) : Validator(true, true, std::cin, get_constraints_file(argc, argv), is_generator_mode(argc, argv)) {}

  private:
	static string get_constraints_file(int argc, char** argv){
		for(int i = 1; i < argc; ++i){
			if(argv[i] == constraints_file_flag){
				if(i + 1 < argc)
					return argv[i+1];
				cerr << constraints_file_flag << " should be followed by a file path!";
				exit(1);
			}
		}
		return {};
	}

	static bool is_generator_mode(int argc, char** argv){
		for(int i = 1; i < argc; ++i){
			if(argv[i] == generate_flag){
				return true;
			}
		}
		return false;
	}
};

class OutputValidator : public Validator {
  public:
	// An OutputValidator can be run in different modes.
	OutputValidator(int argc, char **argv, istream &in_ = std::cin) :
		Validator(is_ws_sensitive(argc, argv), is_case_sensitive(argc, argv), in_) {
	}

  private:
	static bool is_ws_sensitive(int argc, char **argv){
		for(int i = 1; i < argc; ++i) {
			if(argv[i] == ws_sensitive_flag) return true;
		}
		return false;
	}
	static bool is_case_sensitive(int argc, char **argv){
		for(int i = 1; i < argc; ++i) {
			if(argv[i] == case_sensitive_flag) return true;
		}
		return false;
	}
};
