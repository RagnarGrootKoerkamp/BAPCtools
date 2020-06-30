#pragma once
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
#include <array>
#include <cassert>
#include <fstream>
#include <functional>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <random>
#include <set>
#include <stdexcept>
#include <string>
#include <string_view>
#include <type_traits>
#include <utility>
#include <vector>

#ifdef use_source_location
#include <experimental/source_location>
constexpr bool has_source_location = true;
using std::experimental::source_location;
namespace std {
bool operator<(const source_location& l, const source_location& r) { return l.line() < r.line(); }
} // namespace std
#else
constexpr bool has_source_location = false;
struct source_location {
	static source_location current() { return {}; }
	[[nodiscard]] int line() const { return 0; }               // NOLINT
	[[nodiscard]] std::string file_name() const { return ""; } // NOLINT
};
inline bool operator<(const source_location& l, const source_location& r) {
	return l.line() < r.line();
}
#endif

inline std::string location_to_string(source_location loc) {
	return std::string(loc.file_name()) + ":" + std::to_string(loc.line());
}

const std::string_view case_sensitive_flag   = "case_sensitive";
const std::string_view ws_sensitive_flag     = "space_change_sensitive";
const std::string_view constraints_file_flag = "--constraints_file";
const std::string_view generate_flag         = "--generate";

inline struct ArbitraryTag {
	static constexpr bool unique     = false;
	static constexpr bool strict     = false;
	static constexpr bool increasing = false;
	static constexpr bool decreasing = false;
} Arbitrary;
inline struct UniqueTag : ArbitraryTag {
	static constexpr bool unique     = true;
	static constexpr bool strict     = false;
	static constexpr bool increasing = false;
	static constexpr bool decreasing = false;
} Unique;
inline struct IncreasingTag : ArbitraryTag { static constexpr bool increasing = true; } Increasing;
inline struct DecreasingTag : ArbitraryTag { static constexpr bool decreasing = true; } Decreasing;
inline struct StrictlyIncreasingTag : ArbitraryTag {
	static constexpr bool strict     = true;
	static constexpr bool increasing = true;
} StrictlyIncreasing;
inline struct StrictlyDecreasingTag : ArbitraryTag {
	static constexpr bool strict     = true;
	static constexpr bool decreasing = true;
} StrictlyDecreasing;

template <typename... T>
struct Merge : T... {
	static constexpr bool unique     = (T::unique || ...);
	static constexpr bool strict     = (T::strict || ...);
	static constexpr bool increasing = (T::increasing || ...);
	static constexpr bool decreasing = (T::decreasing || ...);
};

template <typename T1, typename T2,
          std::enable_if_t<
              std::is_base_of_v<ArbitraryTag, T1> and std::is_base_of_v<ArbitraryTag, T2>, int> = 0>
auto operator|(T1 /*unused*/, T2 /*unused*/) {
	return Merge<T1, T2>();
}

enum Separator { Space, Newline };

class Validator {
  protected:
	Validator(bool ws_, bool case_, std::istream& in_, std::string constraints_file_path_ = "",
	          std::optional<unsigned int> seed = std::nullopt)
	    : in(in_), ws(ws_), case_sensitive(case_),
	      constraints_file_path(std::move(constraints_file_path_)), gen(bool(seed)),
	      rng(seed.value_or(std::random_device()())) {
		if(gen) return;
		if(ws)
			in >> std::noskipws;
		else
			in >> std::skipws;

		if(!constraints_file_path.empty()) {
			assert(has_source_location); // NOLINT
		}
	}

  public:
	// No copying, no moving.
	Validator(const Validator&) = delete;
	Validator(Validator&&)      = delete;
	void operator=(const Validator&) = delete;
	void operator=(Validator&&) = delete;

	// At the end of the scope, check whether the EOF has been reached.
	// If so, return AC. Otherwise, return WA.
	~Validator() {
		eof();
		write_constraints();
		AC();
	}

	void space() {
		if(gen) {
			out << ' ';
			return;
		}

		if(ws) {
			char c;
			in >> c;
			check(!in.eof(), "Expected space, found EOF.");
			if(c != ' ')
				expected("space", std::string("\"") +
				                      ((c == '\n' or c == '\r') ? std::string("newline")
				                                                : std::string(1, c)) +
				                      "\"");
		}
	}

	void newline() {
		if(gen) {
			out << '\n';
			return;
		}

		if(ws) {
			char c;
			in >> c;
			check(!in.eof(), "Expected newline, found EOF.");
			if(c != '\n') {
				if(c == '\r')
					expected("newline", "DOS line ending (\\r)");
				else
					expected("newline", std::string("\"") + c + "\"");
			}
		}
	}

  private:
	void separator(Separator s) {
		switch(s) {
		case Separator::Space: space(); break;
		case Separator::Newline: newline(); break;
		}
	}

	template <typename T>
	auto& seen() {
		static std::map<source_location, std::set<T>> seen;
		return seen;
	}
	template <typename T>
	auto& last_seen() {
		static std::map<source_location, T> last_seen;
		return last_seen;
	}
	template <typename T>
	auto& integers_seen() {
		static std::map<source_location, std::tuple<std::set<T>, std::vector<T>, bool>>
		    integers_seen;
		return integers_seen;
	}
	template <typename T>
	void reset(source_location loc) {
		seen<T>().erase(loc);
		last_seen<T>().erase(loc);
		integers_seen<T>().erase(loc);
	}

	template <typename T, typename Tag>
	void check_number(const std::string& name, T low, T high, T v, Tag /*unused*/,
	                  source_location loc) {
		static_assert(std::is_same_v<T, long long> or std::is_same_v<T, long double>);
		if(v < low or v > high) {
			std::string type_name;
			if constexpr(std::is_integral_v<T>) { type_name = "integer"; }
			if constexpr(std::is_floating_point_v<T>) { type_name = "float"; }
			expected(name + ": " + type_name + " between " + std::to_string(low) + " and " +
			             std::to_string(high),
			         std::to_string(v));
		}
		log_constraint(name, low, high, v, loc);
		if constexpr(Tag::unique) {
			auto [it, inserted] = seen<T>()[loc].emplace(v);
			check(inserted, name, ": Value ", v, " seen twice, but must be unique!");
		} else {
			auto [it, inserted] = last_seen<T>().emplace(loc, v);
			if(inserted) return;

			auto last  = it->second;
			it->second = v;

			if constexpr(Tag::increasing)
				check(v >= last, name, " is not increasing: value ", v, " follows ", last);
			if constexpr(Tag::decreasing)
				check(v <= last, name, " is not decreasing: value ", v, " follows ", last);
			if constexpr(Tag::strict)
				check(v != last, name, " is not strict: value ", v, " equals ", last);
		}
	}

	template <typename Tag>
	void check_string(const std::string& name, int low, int high, const std::string& v,
	                  Tag /*unused*/, source_location loc) {
		using T = std::string;
		if(v.size() < low or v.size() > high) {
			expected(name + ": " + "string with" + " length between " + std::to_string(low) +
			             " and " + std::to_string(high),
			         v);
		}
		log_constraint(name, low, high, static_cast<int>(v.size()), loc);
		if constexpr(Tag::unique) {
			// static map<source_location, set<T>> seen;
			auto [it, inserted] = seen<T>()[loc].emplace(v);
			check(inserted, name, ": Value ", v, " seen twice, but must be unique!");
		} else if(Tag::increasing or Tag::decreasing) {
			// static map<source_location, T> last_seen;
			auto [it, inserted] = last_seen<T>().emplace(loc, v);
			if(inserted) return;

			auto last  = it->second;
			it->second = v;

			if constexpr(Tag::increasing)
				check(v >= last, name, " is not increasing: value ", v, " follows ", last);
			if constexpr(Tag::decreasing)
				check(v <= last, name, " is not decreasing: value ", v, " follows ", last);
			if constexpr(Tag::strict)
				check(v != last, name, " is not strict: value ", v, " equals ", last);
		}
	}

	// Generate a random integer or float in [low, high].
	template <typename T>
	T uniform_number(T low, T high) {
		assert(low <= high);
		if constexpr(std::is_integral<T>::value)
			return std::uniform_int_distribution<T>(low, high)(rng);
		else
			return std::uniform_real_distribution<T>(low, high)(rng);
	}

	template <typename T, typename Tag>
	T gen_number(const std::string& name, T low, T high, Tag /*unused*/, source_location loc) {
		T v;

		if constexpr(Tag::unique) {
			if constexpr(std::is_integral<T>::value) {
				auto& [seen_here, remaining_here, use_remaining] = integers_seen<T>()[loc];

				if(use_remaining) {
					check(!remaining_here.empty(), name, ": no unique values left");
					v = remaining_here.back();
					remaining_here.pop_back();
				} else {
					do { v = uniform_number(low, high); } while(!seen_here.insert(v).second);

					struct CountIterator {
						using value_type        = T;
						using reference         = T&;
						using pointer           = T;
						using difference_type   = T;
						using iterator_category = std::input_iterator_tag;
						T v;
						T& operator*() { return v; }
						T& operator++() { return ++v; }
						T operator++(int) { return v++; }
						bool operator!=(CountIterator r) { return v != r.v; }
					};

					if(seen_here.size() > (high - low) / 2) {
						use_remaining = true;
						set_difference(CountIterator{low}, CountIterator{high + 1},
						               seen_here.begin(), seen_here.end(),
						               std::back_inserter(remaining_here));
					}
				}
			} else {
				// For floats, just regenerate numbers until success.
				auto& seen_here = seen<T>()[loc];
				do { v = uniform_number(low, high); } while(!seen_here.insert(v).second);
			}

		} else {
			assert(not Tag::increasing && "Generating increasing sequences is not yet supported!");
			assert(not Tag::decreasing && "Generating decreasing sequences is not yet supported!");
			assert((std::is_same<Tag, ArbitraryTag>::value) &&
			       "Only Unique and Arbitrary are supported!");

			v = uniform_number(low, high);
		}

		out << std::setprecision(10) << std::fixed << v;
		return v;
	}

	template <typename T, typename Tag>
	std::vector<T> gen_numbers(const std::string& name, int count, T low, T high, Tag /*unused*/,
	                           Separator sep, source_location loc) {
		std::vector<T> v;
		v.reserve(count);
		if constexpr(std::is_same<Tag, ArbitraryTag>::value) {
			for(int i = 0; i < count; ++i) { v.push_back(uniform_number(low, high)); }
		} else if constexpr(Tag::unique) {
			std::set<T> seen_here;
			if constexpr(std::is_integral<T>::value) {
				if(2 * count < high - low) {
					for(int i = 0; i < count; ++i) {
						// If density < 1/2: retry.
						T w;
						do { w = uniform_number(low, high); } while(!seen_here.insert(w).second);
						v.push_back(w);
					}
				} else {
					// If density >= 1/2, crop a random permutation.
					v.resize(high - low + 1);
					iota(begin(v), end(v), low);
					shuffle(begin(v), end(v), rng);
					v.resize(count);
				}
			} else {
				for(int i = 0; i < count; ++i) {
					// For floats, just regenerate numbers until success.
					T w;
					do { w = uniform_number(low, high); } while(!seen_here.insert(w).second);
					v.push_back(w);
				}
			}
		} else {
			static_assert(Tag::increasing or Tag::decreasing);

			constexpr bool integral_strict = Tag::strict and std::is_integral<T>::value;
			if(integral_strict) high = high - count + 1;

			for(int i = 0; i < count; ++i) v.push_back(uniform_number(low, high));

			sort(begin(v), end(v));

			if(integral_strict) {
				for(int i = 0; i < count; ++i) v[i] += i;
			}

			if(Tag::decreasing) reverse(begin(v), end(v));
		}

		out << std::setprecision(10) << std::fixed;
		for(int i = 0; i < count; ++i) {
			out << v[i];
			if(i < count - 1) separator(sep);
		}
		newline();
		return v;
	}

	template <typename T, typename Tag>
	T read_number(const std::string& name, T low, T high, Tag tag, source_location loc) {
		if(gen) return gen_number(name, low, high, tag, loc);

		const auto v = [&] {
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
	std::vector<T> read_numbers(const std::string& name, int count, T low, T high, Tag tag,
	                            Separator sep, source_location loc) {
		if(gen) return gen_numbers(name, count, low, high, tag, sep, loc);
		reset<T>(loc);
		std::vector<T> v(count);
		for(int i = 0; i < count; ++i) {
			v[i] = read_integer(name);
			check_number(name, low, high, v[i], tag, loc);
			if(i < count - 1) separator(sep);
		}
		newline();
		return v;
	}

  public:
	template <typename Tag = ArbitraryTag>
	long long read_integer(const std::string& name, long long low, long long high, Tag tag = Tag{},
	                       source_location loc = source_location::current()) {
		return read_number(name, low, high, tag, loc);
	}
	template <typename Tag = ArbitraryTag>
	std::vector<long long> read_integers(const std::string& name, int count, long long low,
	                                     long long high, Tag tag = Tag{}, Separator sep = Space,
	                                     source_location loc = source_location::current()) {
		return read_numbers(name, count, low, high, tag, sep, loc);
	}

	template <typename Tag = ArbitraryTag>
	long double read_float(const std::string& name, long double low, long double high,
	                       Tag tag = Tag{}, source_location loc = source_location::current()) {
		return read_number(name, low, high, tag, loc);
	}
	template <typename Tag = ArbitraryTag>
	std::vector<long double> read_floats(const std::string& name, int count, long double low,
	                                     long double high, Tag tag = Tag{}, Separator sep = Space,
	                                     source_location loc = source_location::current()) {
		return read_numbers(name, count, low, high, tag, sep, loc);
	}

	// Read a vector of strings, separated by spaces and ended by a newline.
	template <typename Tag = ArbitraryTag>
	std::vector<std::string> read_strings(const std::string& name, int count, int min, int max,
	                                      const std::string_view chars = "", Tag tag = Tag(),
	                                      Separator sep       = Space,
	                                      source_location loc = source_location::current()) {
		reset<std::string>(loc);
		if(gen) return gen_strings(name, count, min, max, chars, tag, sep, loc);
		assert(!gen);
		std::vector<std::string> v(count);
		for(int i = 0; i < count; ++i) {
			v[i] = read_string(name, min, max, chars);
			check_string(name, min, max, v[i], tag, loc);
			if(i < count - 1) separator(sep);
		}
		newline();
		return v;
	}

	template <typename Tag>
	std::vector<std::string> gen_strings(const std::string& name, int count, int min, int max,
	                                     const std::string_view chars, Tag /*unused*/,
	                                     Separator sep, source_location loc) {
		assert(!chars.empty());

		std::vector<std::string> v(count);
		if constexpr(std::is_same<Tag, ArbitraryTag>::value) {
			for(int i = 0; i < count; ++i) {
				std::string s(uniform_number(min, max), ' ');
				for(auto& x : s) x = chars[uniform_number<int>(0, chars.size() - 1)];
				v.push_back(s);
				out << s;
				if(i < count - 1) separator(sep);
			}
		} else if constexpr(Tag::unique) {
			std::set<std::string> seen_here;
			for(int i = 0; i < count; ++i) {
				// Just regenerate strings until success.
				std::string s;
				do {
					s = std::string(uniform_number(min, max), ' ');
					for(auto& x : s) x = chars[uniform_number<int>(0, chars.size() - 1)];
				} while(!seen_here.insert(s).second);
				v.push_back(s);
				out << s;
				if(i < count - 1) separator(sep);
			}
		} else {
			static_assert(Tag::increasing or Tag::decreasing);

			assert(false && "Generating increasing/decreasing lists of strings is not supported!");
		}

		newline();

		return v;
	}

	// Check the next character.
	bool peek(char c) {
		if(gen) {
			std::bernoulli_distribution dis(0.5);
			return dis(rng);
		}
		if(!ws) in >> std::ws;
		if(case_sensitive) return in.peek() == std::char_traits<char>::to_int_type(c);
		return tolower(in.peek()) == tolower(std::char_traits<char>::to_int_type(c));
	}

	// Read a string and make sure it equals `expected`.
	std::string test_strings(std::vector<std::string> expected) {
		if(gen) {
			int index = expected.size() == 1 ? 0 : uniform_number<int>(0, expected.size() - 1);
			out << expected[index];
			return expected[index];
		}
		std::string s = get_string();
		lowercase(s);

		for(std::string e : expected)
			if(s == lowercase(e)) return s;

		std::string error;
		for(const auto& e : expected) {
			if(not error.empty()) error += "|";
			error += e;
		}
		WA("Expected string \"", error, "\", but found ", s);
	}

	// Read a string and make sure it equals `expected`.
	std::string test_string(std::string expected) { return test_strings({std::move(expected)}); }

	// Read an arbitrary string of a given length.
	std::string read_string(const std::string& name, long long min, long long max,
	                        const std::string_view chars = "",
	                        source_location loc          = source_location::current()) {
		if(gen) {
			assert(!chars.empty());

			std::string s(uniform_number(min, max), ' ');
			for(auto& x : s) x = chars[uniform_number<int>(0, chars.size() - 1)];

			out << s;
			return s;
		}
		std::string s  = get_string();
		long long size = s.size();
		if(size < min || size > max)
			expected(name + ": string of length between " + std::to_string(min) + " and " +
			             std::to_string(max),
			         s);
		std::array<bool, 256> ok_char{};
		if(!chars.empty()) {
			for(auto c : chars) ok_char[c] = true;
			for(auto c : s)
				check(ok_char[c], name, ": expected characters in ", chars, " but found character ",
				      c, " in ", s);
		}
		log_constraint(name, min, max, size, loc);
		return s;
	}

	// Read an arbitrary line of a given length.
	std::string read_line(const std::string& name, long long min, long long max,
	                      const std::string_view chars = "",
	                      source_location loc          = source_location::current()) {
		if(gen) {
			assert(!chars.empty());

			std::string s(uniform_number(min, max), ' ');
			for(auto& x : s) x = chars[uniform_number<int>(0, chars.size() - 1)];

			out << s << '\n';
			return s;
		}

		if(ws) {
			char next = in.peek();
			if(min > 0 and isspace(next))
				expected("non empty line", next == '\n' ? "newline" : "whitespace");
			if(in.eof()) expected("line", "EOF");
		}
		std::string s;
		if(!getline(in, s)) expected("line", "nothing");
		long long size = s.size();
		if(size < min || size > max)
			expected(name + ": line of length between " + std::to_string(min) + " and " +
			             std::to_string(max),
			         s);
		std::array<bool, 256> ok_char{};
		if(!chars.empty()) {
			for(auto c : chars) ok_char[c] = true;
			for(auto c : s)
				check(ok_char[c], name, ": expected characters in ", chars, " but found character ",
				      c, " in ", s);
		}
		log_constraint(name, min, max, size, loc);
		return s;
	}

	// Return ACCEPTED verdict.
	[[noreturn]] void eof_and_AC() {
		eof();
		AC();
	}

  private:
	std::function<void()> WA_handler = [] {};

  public:
	void set_WA_handler(std::function<void()> f) { WA_handler = std::move(f); }

	// Return WA with the given reason.
	template <typename... Ts>
	[[noreturn]] void WA(Ts... ts) {
		static_assert(sizeof...(Ts) > 0);

		WA_handler();

		auto pos = get_file_pos();
		std::cerr << pos.first << ":" << pos.second << ": ";

		WA_impl(ts...);
	}

	// Check that the condition is true.
	template <typename... Ts>
	void check(bool b, Ts... ts) {
		static_assert(sizeof...(Ts) > 0, "Provide a non-empty error message.");

		if(!b) WA(ts...);
	}

	// Log some value in a range.
	template <typename T>
	void log_constraint(const std::string& name, T low, T high, T v,
	                    source_location loc = source_location::current()) {
		// Do not log when line number is unknown/default/unsupported.
		if(loc.line() == 0 or constraints_file_path.empty()) return;

		auto [it, inserted] = [&] {
			if constexpr(std::is_integral<T>::value)
				return integer_bounds.emplace(loc, Bounds<long long>(name, v, v, low, high));
			else
				return float_bounds.emplace(loc, Bounds<long double>(name, v, v, low, high));
		}();
		auto& done = it->second;
		if(inserted) {
			assert(!name.empty() && "Variable names must not be empty.");
			assert(name.find(' ') == std::string::npos && "Variable name must not contain spaces.");
		} else {
			assert(name == done.name && "Variable name must be constant.");
		}
		if(v < done.min) {
			done.min = v;
			done.low = low;
		}
		if(v > done.max) {
			done.max  = v;
			done.high = high;
		}
		done.has_min |= v == low;
		done.has_max |= v == high;
	}

  private:
	long long read_integer(const std::string& name) {
		if(gen) {
			std::uniform_int_distribution<long long> dis(std::numeric_limits<long long>::lowest(),
			                                             std::numeric_limits<long long>::max());
			auto v = dis(rng);
			out << v;
			return v;
		}
		std::string s = get_string("integer");
		if(s.empty()) { WA(name, ": Want integer, found nothing"); }
		long long v;
		try {
			size_t chars_processed = 0;
			v                      = stoll(s, &chars_processed);
			if(chars_processed != s.size())
				WA(name, ": Parsing " + s + " as long long failed! Did not process all characters");
		} catch(const std::out_of_range& e) {
			WA(name, ": Number " + s + " does not fit in a long long!");
		} catch(const std::invalid_argument& e) { WA("Parsing " + s + " as long long failed!"); }
		// Check for leading zero.
		if(v == 0) {
			if(s.size() != 1) WA(name, ": Parsed 0, but has leading 0 or minus sign: ", s);
		}
		if(v > 0) {
			if(s[0] == '0') WA(name, ": Parsed ", v, ", but has leading 0: ", s);
		}
		if(v < 0) {
			if(s.size() <= 1) WA(name, ": Parsed ", v, ", but string is: ", s);
			if(s[1] == '0') WA(name, ": Parsed ", v, ", but has leading 0: ", s);
		}
		return v;
	}

	long double read_float(const std::string& name) {
		if(gen) {
			std::uniform_real_distribution<long double> dis(
			    std::numeric_limits<long double>::lowest(),
			    std::numeric_limits<long double>::max());
			auto v = dis(rng);
			out << std::setprecision(10) << std::fixed << v;
			return v;
		}
		std::string s = get_string("long double");
		long double v;
		try {
			size_t chars_processed;
			v = stold(s, &chars_processed);
			if(chars_processed != s.size())
				WA(name, ": Parsing ", s,
				   " as long double failed! Did not process all characters.");
		} catch(const std::out_of_range& e) {
			WA(name, ": Number " + s + " does not fit in a long double!");
		} catch(const std::invalid_argument& e) { WA("Parsing " + s + " as long double failed!"); }
		return v;
	}

	[[noreturn]] void expected(const std::string& exp = "", const std::string& s = "") {
		assert(!gen && "Expected is not supported for generators.");
		if(!s.empty())
			WA("Expected ", exp, ", found ", s);
		else
			WA(exp);
	}

	template <typename T>
	[[noreturn]] void WA_impl(T t) {
		std::cerr << t << std::endl;
		exit(ret_WA);
	}

	std::pair<int, int> get_file_pos() {
		int line = 1, col = 0;
		in.clear();
		auto originalPos = in.tellg();
		if(originalPos < 0) return {-1, -1};
		in.seekg(0);
		char c;
		while((in.tellg() < originalPos) && in.get(c)) {
			if(c == '\n')
				++line, col = 0;
			else
				++col;
		}
		return {line, col};
	}

	// Keep track of the min/max value read at every call site.
	template <typename T>
	struct Bounds {
		Bounds(std::string name_, T min_, T max_, T low_, T high_)
		    : name(std::move(name_)), min(min_), max(max_), low(low_), high(high_) {} // NOLINT
		std::string name;
		T min, max;  // Smallest / largest value observed
		T low, high; // Bounds
		bool has_min = false, has_max = false;
	};

	template <typename T, typename... Ts>
	[[noreturn]] void WA_impl(T t, Ts... ts) {
		std::cerr << t;
		WA_impl(ts...);
	}

	std::string get_string(const std::string& wanted = "string") {
		assert(!gen && "get_string is not supported for generators.");
		if(ws) {
			char next = in.peek();
			if(isspace(next)) expected(wanted, next == '\n' ? "newline" : "whitespace");
			if(in.eof()) expected(wanted, "EOF");
		}
		std::string s;
		if(in >> s) return s;
		expected(wanted, "nothing");
	}

	// Return ACCEPTED verdict.
	[[noreturn]] void AC() const {
		if(gen) exit(0);

		exit(ret_AC);
	}

	void eof() {
		if(gen) return;
		if(in.eof()) return;
		// Sometimes EOF hasn't been triggered yet.
		if(!ws) in >> std::ws;
		char c = in.get();
		if(c == std::char_traits<char>::eof()) return;
		std::string got = std::string("\"") + char(c) + '"';
		if(c == '\n') got = "newline";
		expected("EOF", got);
	}

	// Convert a string to lowercase is matching is not case sensitive.
	std::string& lowercase(std::string& s) const {
		if(case_sensitive) return s;
		transform(s.begin(), s.end(), s.begin(), [](unsigned char c) { return std::tolower(c); });
		return s;
	}

	std::map<source_location, Bounds<long long>> integer_bounds;
	std::map<source_location, Bounds<long double>> float_bounds;

	void write_constraints() {
		if(constraints_file_path.empty()) return;

		std::ofstream os(constraints_file_path);

		for(const auto& d : integer_bounds)
			os << location_to_string(d.first) << " " << d.second.name << " " << d.second.has_min
			   << " " << d.second.has_max << " " << d.second.min << " " << d.second.max << " "
			   << d.second.low << " " << d.second.high << std::endl;
		for(const auto& d : float_bounds)
			os << location_to_string(d.first) << " " << d.second.name << " " << d.second.has_min
			   << " " << d.second.has_max << " " << d.second.min << " " << d.second.max << " "
			   << d.second.low << " " << d.second.high << std::endl;
	}

	static const int ret_AC = 42, ret_WA = 43;
	std::istream& in          = std::cin;
	std::ostream& out         = std::cout;
	const bool ws             = true;
	const bool case_sensitive = true;
	const std::string constraints_file_path;
	const bool gen = false;

	std::mt19937_64 rng;

  protected:
	static std::string get_constraints_file(int argc, char** argv) {
		for(int i = 1; i < argc; ++i) {
			if(argv[i] == constraints_file_flag) {
				if(i + 1 < argc) return argv[i + 1];
				std::cerr << constraints_file_flag << " should be followed by a file path!";
				exit(1);
			}
		}
		return {};
	}
};

class InputValidator : public Validator {
  public:
	// An InputValidator is always both whitespace and case sensitive.
	explicit InputValidator(int argc = 0, char** argv = nullptr)
	    : Validator(true, true, std::cin, get_constraints_file(argc, argv), get_seed(argc, argv)) {}

  private:
	static std::optional<unsigned int> get_seed(int argc, char** argv) {
		for(int i = 1; i < argc - 1; ++i) {
			if(argv[i] == generate_flag) { return std::stol(argv[i + 1]); }
		}
		return std::nullopt;
	}
};

class OutputValidator : public Validator {
  public:
	// An OutputValidator can be run in different modes.
	explicit OutputValidator(int argc, char** argv, std::istream& in_ = std::cin)
	    : Validator(is_ws_sensitive(argc, argv), is_case_sensitive(argc, argv), in_,
	                get_constraints_file(argc, argv)) {}

  private:
	static bool is_ws_sensitive(int argc, char** argv) {
		for(int i = 1; i < argc; ++i) {
			if(argv[i] == ws_sensitive_flag) return true;
		}
		return false;
	}
	static bool is_case_sensitive(int argc, char** argv) {
		for(int i = 1; i < argc; ++i) {
			if(argv[i] == case_sensitive_flag) return true;
		}
		return false;
	}
};
