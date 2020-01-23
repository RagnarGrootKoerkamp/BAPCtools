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
#include <set>
#include <vector>
#include <type_traits>
#include <random>
#include <string>
#include <string_view>
#include <functional>

// Used for order statistics tree.
#include <ext/pb_ds/assoc_container.hpp>
#include <ext/pb_ds/tree_policy.hpp>

#ifdef use_source_location
#include <experimental/source_location>
using std::experimental::source_location;
#else
struct source_location {
	static source_location current(){ return {}; }
	int line() const { return 0; }
	std::string file_name() const { return ""; }
};
#endif

bool operator<(const source_location& l, const source_location& r){
	return l.line() < r.line();
}
std::string to_string(source_location loc){
	return std::string(loc.file_name())+":"+std::to_string(loc.line());
}

using namespace std;

const string case_sensitive_flag = "case_sensitive";
const string ws_sensitive_flag = "space_change_sensitive";
const string constraints_file_flag = "--constraints_file";
const string generate_flag = "--generate";

struct ArbitraryTag {
	static constexpr bool unique = false;
	static constexpr bool strict = false;
	static constexpr bool increasing = false;
	static constexpr bool decreasing = false;
} Arbitrary;
struct UniqueTag {
	static constexpr bool unique = true;
	static constexpr bool strict = false;
	static constexpr bool increasing = false;
	static constexpr bool decreasing = false;
} Unique;
struct IncreasingTag {
	static constexpr bool unique = false;
	static constexpr bool strict = false;
	static constexpr bool increasing = true;
	static constexpr bool decreasing = false;
} Increasing;
struct DecreasingTag {
	static constexpr bool unique = false;
	static constexpr bool strict = false;
	static constexpr bool increasing = false;
	static constexpr bool decreasing = true;
} Decreasing;
struct StrictlyIncreasingTag {
	static constexpr bool unique = false;
	static constexpr bool strict = true;
	static constexpr bool increasing = true;
	static constexpr bool decreasing = false;
} StrictlyIncreasing;
struct StrictlyDecreasingTag {
	static constexpr bool unique = false;
	static constexpr bool strict = true;
	static constexpr bool increasing = false;
	static constexpr bool decreasing = true;
} StrictlyDecreasing;


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


  private:
	template<typename T, typename Tag>
	void check_number(const string& name, T low, T high, T v, Tag, source_location loc){
		if(v < low or v > high){
			expected(name + ": " + typeid(T).name() + " between " + to_string(low) + " and " + to_string(high), to_string(v));
		}
		log_constraint(low, high, v, loc);
		if constexpr(Tag::unique){
			static map<source_location, set<T>> seen;
			auto [it, inserted] = seen[loc].emplace(v);
			check(inserted, name, ": Value ", v, " seen twice, but must be unique!");
		} else {
			static map<source_location, T> last_map;
			auto [it, inserted] = last_map.emplace(loc, v);
			if(inserted) return;

			auto last = it->second;
			it->second = v;

			if constexpr(Tag::increasing) check(v >= last, name, " is not increasing: value ", v, " follows ", last);
			if constexpr(Tag::decreasing) check(v <= last, name, " is not decreasing: value ", v, " follows ", last);
			if constexpr(Tag::strict) check(v != last, name, " is not strict: value ", v, " equals ", last);
		}
	}

	template<typename T>
	T uniform_number(T low, T high){
		assert(low <= high);
		if constexpr(std::is_integral<T>::value)
			return std::uniform_int_distribution<T>(low, high)(rng);
		else
			return std::uniform_real_distribution<T>(low, high)(rng);
	}

	template<typename T, typename Tag>
	T gen_number(const string& name, T low, T high, Tag, source_location loc){
		T v;

		if constexpr(Tag::unique){
			if constexpr(std::is_integral<T>::value){
				static map<source_location, tuple<set<T>, vector<T>, bool>> seen;

				auto& [seen_here, remaining_here, use_remaining] = seen[loc];

				if(use_remaining){
					check(!remaining_here.empty(), name, ": no unique values left");
					v = remaining_here.back();
					remaining_here.pop_back();
				} else {
					do {
						v = uniform_number(low, high);
					} while(!seen_here.insert(v).second);

					struct CountIterator{
						using value_type = T;
						using reference = T&;
						using pointer = T;
						using difference_type = T;
						using iterator_category = std::input_iterator_tag;
						T v;
						T& operator*(){ return v; }
						T& operator++(){ return ++v; }
						T operator++(int){ return v++; }
						bool operator!=(CountIterator r){ return v != r.v; }
					};

					if(seen_here.size() > (high-low)/2){
						use_remaining=true;
						set_difference(CountIterator{low}, CountIterator{high+1}, seen_here.begin(), seen_here.end(), std::back_inserter(remaining_here));
					}
				}
			} else {
				static map<source_location, set<T>> seen;

				// For floats, just regenerate numbers until success.
				auto& seen_here = seen[loc];
				do {
					v = uniform_number(low, high);
				} while(!seen_here.insert(v).second);
			}

		} else {
			assert(not Tag::increasing && "Generating increasing sequences is not yet supported!");
			assert(not Tag::decreasing && "Generating decreasing sequences is not yet supported!");
			assert((std::is_same<Tag, ArbitraryTag>::value) && "Only Unique and Arbitrary are supported!");

			v = uniform_number(low, high);
		}

		out << setprecision(10) << fixed << v;
		return v;
	}

	template<typename T, typename Tag>
	std::vector<T> gen_numbers(const string& name, int count, T low, T high, Tag, source_location loc){
		std::vector<T> v;
		v.reserve(count);
		if constexpr(std::is_same<Tag, ArbitraryTag>::value){
			for(int i = 0; i < count; ++i){
				v.push_back(uniform_number(low, high));
			}
		} else if constexpr(Tag::unique){
			set<T> seen_here;
			if constexpr(std::is_integral<T>::value){
				if(2*count < high-low){
					for(int i = 0; i < count; ++i){
						// If density < 1/2: retry.
						T w;
						do {
							w = uniform_number(low, high);
						} while(!seen_here.insert(w).second);
						v.push_back(w);
					}
				} else {
					// If density >= 1/2, crop a random permutation.
					v.resize(high-low+1);
					iota(begin(v), end(v), low);
					shuffle(begin(v), end(v), rng);
					v.resize(count);
				}
			} else {
				for(int i = 0; i < count; ++i){
					// For floats, just regenerate numbers until success.
					T w;
					do {
						w = uniform_number(low, high);
					} while(!seen_here.insert(w).second);
					v.push_back(w);
				}
			}
		} else {
			static_assert(Tag::increasing or Tag::decreasing);

			constexpr bool integral_strict = Tag::strict and std::is_integral<T>::value;
			if(integral_strict) high = high - count + 1;

			for(int i = 0; i < count; ++i)
				v.push_back(uniform_number(low, high));

			sort(begin(v), end(v));

			if(integral_strict){
				for(int i = 0; i < count; ++i)
					v[i] += i;
			}

			if(Tag::decreasing) reverse(begin(v), end(v));
		}

		out << setprecision(10) << fixed;
		for(int i = 0; i < count; ++i){
			out << v[i];
			if(i < count-1) space();
		}
		newline();
		return v;
	}


	template <typename T, typename Tag>
	T read_number(const string& name, T low, T high, Tag tag, source_location loc) {
		if(gen) return gen_number(name, low, high, tag, loc);

		const auto v = [&]{
			if constexpr(std::is_integral<T>::value)
				return read_integer(name);
			else
				return read_float(name);
		}();

		check_number(name, low, high, v, tag, loc);
		return v;
	}

	// Read a vector of numbers, separated by spaces and ended by a newline.
	template <typename T, typename Tag>
	std::vector<T> read_numbers(const string& name, int count, T low, T high, Tag tag, source_location loc) {
		if(gen) return gen_numbers(name, count, low, high, tag, loc);
		std::vector<T> v(count);
		for(int i = 0; i < count; ++i){
			v[i] = read_integer(name);
			check_number(name, low, high, v[i], tag, loc);
			if(i < count-1) space();
		}
		newline();
		return v;
	}

  public:
	template <typename Tag=ArbitraryTag>
	long long read_integer(const string& name, long long low, long long high, Tag tag=Tag{}, source_location loc = source_location::current()) {
		return read_number(name, low, high, tag, loc);
	}
	template <typename Tag=ArbitraryTag>
	std::vector<long long> read_integers(const string& name, int count, long long low, long long high, Tag tag=Tag{}, source_location loc = source_location::current()) {
		return read_numbers(name, count, low, high, tag, loc);
	}

	template <typename Tag=ArbitraryTag>
	long double read_float(const string& name, long double low, long double high, Tag tag=Tag{}, source_location loc = source_location::current()) {
		return read_number(name, low, high, tag, loc);
	}
	template <typename Tag=ArbitraryTag>
	std::vector<long double> read_floats(const string& name, int count, long double low, long double high, Tag tag=Tag{}, source_location loc = source_location::current()) {
		return read_numbers(name, count, low, high, tag, loc);
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



	// Read a string and make sure it equals `expected`.
	string test_string(string expected) {
		if(gen){
			out << expected;
			return expected;
		}
	   	return read_string_impl(expected);
   	}

	// Read an arbitrary string of a given length.
	string read_string(const string& name, long long min, long long max, const std::string_view chars = "", source_location loc = source_location::current()) {
		if(gen){
			assert(!chars.empty());

			string s(uniform_number(min, max), ' ');
			for(auto &x : s) x = chars[uniform_number(0, (int)chars.size()-1)];

			out << s;
			return s;
		}
		assert(!gen && "Generating strings is not supported!");
		string s = read_string_impl();
		long long size = s.size();
		if(size < min || size > max)
			expected(name + ": string of length between " + to_string(min) + " and " + to_string(max), s);
		std::array<bool, 256> ok_char;
		ok_char.fill(false);
		if(!chars.empty()){
			for(auto c : chars) ok_char[c] = true;
			for(auto c : s) check(ok_char[c], name, ": expected characters in ", chars, " but found ", c);
		}
		log_constraint(min, max, size, loc);
		return s;
	}

    std::function<void()> WA_handler = []{};
    void set_WA_handler(std::function<void()> f){
        WA_handler = std::move(f);
    }

	// Return WA with the given reason.
	template <typename... Ts>
	[[noreturn]] void WA(Ts... ts) {
        static_assert(sizeof...(Ts) > 0);

		WA_handler();

		auto pos = get_file_pos();
		cerr << pos.first << ":" << pos.second << ": ";

		WA_impl(ts...);
	}

	// Check that the condition is true.
	template <typename... Ts>
	void check(bool b, Ts... ts) {
        static_assert(sizeof...(Ts) > 0);

		if(!b) WA(ts...);
	}

	// Log some value in a range.
	template<typename T>
	void log_constraint(T low, T high, T v, source_location loc = source_location::current()){
		// Do not log when line number is unknown/default/unsupported.
		if(loc.line() == 0 or constraints_file_path.empty()) return;

		auto& done = [&]() -> auto& {
			if constexpr(std::is_integral<T>::value)
				return integer_bounds.emplace(loc, Bounds<long long>(v, v, low, high)).first->second;
			else
				return float_bounds.emplace(loc, Bounds<long double>(v, v, low, high)).first->second;
		}();
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
	long long read_integer(const string& name) {
		if(gen){
			std::uniform_int_distribution<long long> dis(std::numeric_limits<long long>::lowest(), std::numeric_limits<long long>::max());
			auto v = dis(rng);
			out << v;
			return v;
		}
		string s = read_string_impl("", "integer");
		if(s.empty()){
			WA(name, ": Want integer, found nothing");
		}
		long long v;
		try {
			size_t chars_processed = 0;
			v                      = stoll(s, &chars_processed);
			if(chars_processed != s.size())
				WA(name, ": Parsing " + s + " as long long failed! Did not process all characters");
		} catch(const out_of_range &e) {
			WA(name, ": Number " + s + " does not fit in a long long!");
		} catch(const invalid_argument &e) { WA("Parsing " + s + " as long long failed!"); }
		// Check for leading zero.
		if(v == 0){
			if(s.size() != 1)
				WA(name, ": Parsed 0, but has leading 0 or minus sign: " , s);
		}
		if(v > 0){
			if(s[0] == '0')
				WA(name, ": Parsed ",v,", but has leading 0: " , s);
		}
		if(v < 0){
			if(s.size() <= 1)
				WA(name, ": Parsed ",v,", but string is: " , s);
			if(s[1] == '0')
				WA(name, ": Parsed ",v,", but has leading 0: " , s);
		}
		return v;
	}

	long double read_float(const string& name) {
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
				WA(name, ": Parsing ", s, " as long double failed! Did not process all characters.");
		} catch(const out_of_range &e) {
			WA(name, ": Number " + s + " does not fit in a long double!");
		} catch(const invalid_argument &e) { WA("Parsing " + s + " as long double failed!"); }
		return v;
	}

	[[noreturn]] void expected(string exp = "", string s = "") {
		assert(!gen && "Expected is not supported for generators.");
		if(!s.empty())
			WA("Expected ", exp, ", found ", s);
		else
			WA(exp);
	}

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
		if(gen) exit(0);

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
		Bounds(T min_, T max_, T low_, T high_) : min(min_), max(max_), low(low_), high(high_) {}
		T min, max;  // Smallest / largest value observed
		T low, high; // Bounds
		bool has_min=false, has_max=false;
	};

	map<source_location, Bounds<long long>> integer_bounds;
	map<source_location, Bounds<long double>> float_bounds;

	void write_constraints(){
		if(constraints_file_path.empty()) return;

		ofstream os(constraints_file_path);

		for(const auto& d : integer_bounds)
			os << to_string(d.first) << " " << d.second.has_min << " " << d.second.has_max << " " << d.second.min << " " << d.second.max << " " << d.second.low << " " << d.second.high << endl;
		for(const auto& d : float_bounds)
			os << to_string(d.first) << " " << d.second.has_min << " " << d.second.has_max << " " << d.second.min << " " << d.second.max << " " << d.second.low << " " << d.second.high << endl;
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
