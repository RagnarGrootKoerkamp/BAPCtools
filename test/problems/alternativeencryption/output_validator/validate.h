//============================================================================//
// validate.h                                                                 //
//============================================================================//
// this is a minimized version of the validate.h header
//============================================================================//
// version 2.6.3                                                              //
// https://github.com/mzuenni/icpc-header                                     //
//============================================================================//

#ifndef VALIDATE_H
#define VALIDATE_H

#include <algorithm>
#include <array>
#include <bitset>
#include <cctype>
#include <cmath>
#include <charconv>
#include <complex>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <numeric>
#include <optional>
#include <queue>
#include <random>
#include <regex>
#include <set>
#include <string>
#include <string_view>
#include <typeinfo>
#include <typeindex>
#include <type_traits>
#include <utility>
#include <variant>
#include <vector>


//============================================================================//
// Basic definitions and constants                                            //
//============================================================================//
// default types
using Integer = std::int64_t;
using Real = long double;

// derived types
using UInteger = std::make_unsigned<Integer>::type;
constexpr Integer operator ""_int(unsigned long long int value) {return static_cast<Integer>(value);}
constexpr UInteger operator ""_uint(unsigned long long int value) {return static_cast<UInteger>(value);}
constexpr Real operator ""_real(unsigned long long int value) {return static_cast<Real>(value);}
constexpr Real operator ""_real(long double value) {return static_cast<Real>(value);}

// settings which can be overwritten before the include!
//#define DOUBLE_FALLBACK
namespace Settings {
	namespace details {
		using RandomEngine                              = std::mt19937_64;
		constexpr Integer LARGE                         = 0x3FFF'FFFF'FFFF'FFFF;
		constexpr bool DEFAULT_CASE_LOWER               = true;
		constexpr int DEFAULT_PRECISION                 = 6;
		constexpr Real DEFAULT_EPS                      = 1e-6_real;

		[[noreturn]] void exitVerdict(int exitCode) {
			//throw exitCode;
			//quick_exit(exitCode);
			std::exit(exitCode);
		}
	}
	using namespace details;
}
// make settings publically available
using Settings::RandomEngine;
using Settings::LARGE;
using Settings::DEFAULT_CASE_LOWER;
using Settings::DEFAULT_PRECISION;
using Settings::DEFAULT_EPS;
using Settings::exitVerdict;

// useful constants
constexpr std::string_view LETTER                       = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";
constexpr std::string_view UPPER                        = LETTER.substr(0, 26);
constexpr std::string_view LOWER                        = LETTER.substr(26);
constexpr std::string_view VOWEL                        = "AEIOUaeiou";
constexpr std::string_view UPPER_VOWELS                 = VOWEL.substr(0, 5);
constexpr std::string_view LOWER_VOWELS                 = VOWEL.substr(5);
constexpr std::string_view CONSONANT                    = "BCDFGHJKLMNPQRSTVWXYZbcdfghjklmnpqrstvwxyz";
constexpr std::string_view UPPER_CONSONANT              = CONSONANT.substr(0, 26 - 5);
constexpr std::string_view LOWER_CONSONANT              = CONSONANT.substr(26 - 5);
constexpr std::string_view ALPHA_NUMERIC                = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";
constexpr std::string_view UPPER_ALPHA_NUMERIC          = ALPHA_NUMERIC.substr(0, 10 + 26);
constexpr std::string_view LOWER_ALPHA_NUMERIC          = "0123456789abcdefghijklmnopqrstuvwxyz";
constexpr std::string_view DIGITS                       = ALPHA_NUMERIC.substr(0, 10);
constexpr std::string_view BRACKETS                     = "()[]{}<>";
constexpr char NEWLINE                                  = '\n';
constexpr char SPACE                                    = ' ';
constexpr char NOSEP                                    = '\0';
constexpr Real PI                                       = 3.1415926535897932384626433832795028_real;


//============================================================================//
// internal definitions and constants                                         //
//============================================================================//
constexpr UInteger DEFAULT_SEED                         = 3141592653589793238_uint;
constexpr std::string_view CASE_SENSITIVE               = "case_sensitive";
constexpr std::string_view SPACE_SENSITIVE              = "space_change_sensitive";
constexpr std::string_view FLOAT_ABSOLUTE_TOLERANCE     = "float_absolute_tolerance";
constexpr std::string_view FLOAT_RELATIVE_TOLERANCE     = "float_relative_tolerance";
constexpr std::string_view FLOAT_TOLERANCE              = "float_tolerance";
constexpr std::string_view JUDGE_MESSAGE                = "judgemessage.txt";
constexpr std::string_view TEAM_MESSAGE                 = "teammessage.txt";
constexpr std::ios_base::openmode MESSAGE_MODE          = std::ios::out;
constexpr char DEFAULT_SEPARATOR                        = SPACE;
constexpr std::string_view EMPTY_COMMAND                = "";
constexpr std::string_view COMMAND_PREFIX               = "--";
constexpr std::string_view CONSTRAINT_COMMAND           = "--constraints_file";
constexpr std::string_view SEED_COMMAND                 = "--seed";
constexpr std::string_view TEXT_ELLIPSIS                = "[...]";
constexpr auto REGEX_OPTIONS                            = std::regex::nosubs | std::regex::optimize;
inline const std::regex INTEGER_REGEX("0|-?[1-9][0-9]*", REGEX_OPTIONS);
inline const std::regex REAL_REGEX("[+-]?(([0-9]*\\.[0-9]+)|([0-9]+\\.)|([0-9]+))([eE][+-]?[0-9]+)?", REGEX_OPTIONS);
inline const std::regex STRICT_REAL_REGEX("-?(0|([1-9][0-9]*))\\.?[0-9]*", REGEX_OPTIONS);

static_assert(2'000'000'000'000'000'000_int < LARGE / 2, "LARGE too small");
static_assert(LARGE <= std::numeric_limits<Integer>::max() / 2, "LARGE too big");

static_assert(-1 == 0xFFFF'FFFF'FFFF'FFFF_int, "Two's complement for signed numbers is required" );
static_assert(std::is_convertible_v<Integer, UInteger>, "Incompatible Integer and UInteger types?!");
static_assert(std::is_convertible_v<UInteger, Integer>, "Incompatible Integer and UInteger types?!");
static_assert(sizeof(Integer) == sizeof(UInteger), "Incompatible Integer and UInteger types?!");

template<typename T = std::logic_error>
constexpr void judgeAssert(bool asserted, std::string_view message) {
	if (!asserted) throw T(message.data());
}


//============================================================================//
// SFINAE                                                                     //
//============================================================================//
namespace details {
	template<typename T, typename = void>
	struct IsContainer : std::false_type {};

	template<typename T>
	struct IsContainer<T, std::void_t<decltype(std::begin(std::declval<std::add_lvalue_reference_t<T>>()))>> : std::true_type {
		using iterator_type = decltype(std::begin(std::declval<std::add_lvalue_reference_t<T>>()));
		using value_type = std::remove_reference_t<decltype(*std::begin(std::declval<std::add_lvalue_reference_t<T>>()))>;
	};

	template<typename T>
	struct IsStdArray : std::false_type {};

	template<typename T, std::size_t N>
	struct IsStdArray<std::array<T, N>> : std::true_type {};

	template<typename T, typename = void>
	struct IsTupleLike : std::false_type {};

	template<typename T>
	struct IsTupleLike<T, std::void_t<decltype(sizeof(std::tuple_size<T>))>> : std::true_type {};

	template<typename T, typename = void>
	struct HasOstreamOperator : std::false_type {};

	template<typename T>
	struct HasOstreamOperator<T, std::void_t<decltype(std::declval<std::ostream>() << std::declval<T>())>> : std::true_type {};
}


//============================================================================//
// Verdicts                                                                   //
//============================================================================//
namespace Verdicts {
	struct Verdict final {
		int exitCode;

		constexpr explicit Verdict(int exitCode_ = 1) : exitCode(exitCode_) {}

		constexpr operator int() const {
			return exitCode;
		}

		[[noreturn]] void exit() const {
			exitVerdict(exitCode);
		}

		friend void operator<<(std::ostream& os, const Verdict& v) {
			os << std::endl;
			v.exit();
		}
	};

	// default verdicts (we do not support scoring)
	constexpr Verdict AC(42);
	constexpr Verdict WA(43);
	constexpr Verdict PE = WA;
	constexpr Verdict FAIL(1);
}


//============================================================================//
// Output streams                                                             //
//============================================================================//
class NullStream final : public std::ostream {
	class NullBuffer final : public std::streambuf {
	protected:
		std::streamsize xsputn(const char* /**/, std::streamsize n) override {
			return n;
		}
		int overflow(int c = std::char_traits<char>::eof()) override {
			return std::char_traits<char>::not_eof(c);
		}
	} nullBuffer;
public:
	NullStream() : std::ostream(&nullBuffer) {}
};

namespace details {
	NullStream nullStream;
}

class OutputStream final {
	std::unique_ptr<std::ofstream> managed;
	std::ostream* os;

	void init() {
		*os << std::boolalpha;
		*os << std::fixed;
		*os << std::setprecision(DEFAULT_PRECISION);
	}

public:
	OutputStream() : os(&details::nullStream) {}
	OutputStream(std::ostream& os_) : os(&os_) {init();}
	explicit OutputStream(const std::filesystem::path& path, std::ios_base::openmode mode) : managed(std::make_unique<std::ofstream>(path, mode)), os(managed.get()) {
		judgeAssert<std::runtime_error>(os->good(), "OutputStream(): Could not open File: " + path.string());
		init();
	}

	OutputStream(OutputStream&& other) = default;
	OutputStream& operator=(OutputStream&& other) = default;

	OutputStream(const OutputStream&) = delete;
	OutputStream& operator=(const OutputStream&) = delete;

	template<typename L, typename R>
	OutputStream& operator<<(const std::pair<L, R>& t) {
		return *this << t.first << DEFAULT_SEPARATOR << t.second;
	}

	template<typename... Args>
	OutputStream& operator<<(const std::tuple<Args...>& t) {
		return join(t, std::index_sequence_for<Args...>(), DEFAULT_SEPARATOR);
	}

	template<typename T>
	OutputStream& operator<<(const T& x) {
		if constexpr ((std::is_array_v<T> and !std::is_same_v<std::decay_t<T>, char*>) or
		              (details::IsContainer<T>{} and !details::HasOstreamOperator<T>{})) {
			return join(std::begin(x), std::end(x), DEFAULT_SEPARATOR);
		} else {
			*os << x;
			return *this;
		}
	}

	OutputStream& operator<<(std::ostream& (*manip)(std::ostream&)) {
		*os << manip;
		return *this;
	}

	template<typename Tuple, std::size_t... Is>
	OutputStream& join(const Tuple& t, std::index_sequence<Is...> /**/, char separator) {
		static_assert(std::tuple_size_v<Tuple> == sizeof...(Is));
		if (separator != NOSEP) ((*os << (Is == 0 ? std::string_view() : std::string_view(&separator, 1)), *this << std::get<Is>(t)), ...);
		else ((*this << std::get<Is>(t)), ...);
		return *this;
	}

	template<typename T>
	OutputStream& join(T first, T last, char separator) {
		for (auto it = first; it != last; it++) {
			if (it != first and separator != NOSEP) *os << separator;
			*this << *it;
		}
		return *this;
	}
};

namespace ValidateBase {
	// define this early so everyone can use it!
	OutputStream juryErr(std::cerr);
	OutputStream juryOut(std::cout);
}

template<typename T>
struct boolean {
	bool value;
	std::optional<T> reason;

	constexpr boolean(bool value_) : value(value_) {}
	constexpr boolean(bool value_, const T& reason_) : value(value_), reason(reason_) {}

	constexpr operator bool() const {
		return value;
	}

	constexpr bool hasReason() const {
		return reason.has_value();
	}
};

// for strings (cctype functions are not safe to use with char...)
constexpr bool isLower(char c) {
	return c >= 'a' and c <= 'z';
}

constexpr bool isUpper(char c) {
	return c >= 'A' and c <= 'Z';
}

constexpr bool isLetter(char c) {
	return isLower(c) or isUpper(c);
}

constexpr bool isDigit(char c) {
	return c >= '0' and c <= '9';
}

constexpr char toLower(char c) {
	if (isUpper(c)) c += 'a' - 'A';
	return c;
}

constexpr bool isVowel(char c) {
	c = toLower(c);
	for (char x : LOWER_VOWELS) {
		if (c == x) return true;
	}
	return false;
}

constexpr bool isConsonant(char c) {
	return isLetter(c) and !isVowel(c);
}

constexpr char toUpper(char c) {
	if (isLower(c)) c -= 'a' - 'A';
	return c;
}

constexpr char toDefaultCase(char c) {
	if constexpr (DEFAULT_CASE_LOWER) return toLower(c);
	return toUpper(c);
}

void toLower(std::string& s) {
	for (char& c : s) c = toLower(c);
}

void toUpper(std::string& s) {
	for (char& c : s) c = toUpper(c);
}

void toDefaultCase(std::string& s) {
	if constexpr (DEFAULT_CASE_LOWER) return toLower(s);
	return toUpper(s);
}

constexpr bool isLower(std::string_view s) {
	for (char c : s) if (!isLower(c)) return false;
	return true;
}

constexpr boolean<char> isUpper(std::string_view s) {
	for (char c : s) if (!isUpper(c)) return boolean<char>(false, c);
	return boolean<char>(true);
}

constexpr boolean<char> isLetter(std::string_view s) {
	for (char c : s) if (!isLetter(c)) return boolean<char>(false, c);
	return boolean<char>(true);
}

constexpr boolean<char> isDigit(std::string_view s) {
	for (char c : s) if (!isDigit(c)) return boolean<char>(false, c);
	return boolean<char>(true);
}

constexpr boolean<char> isVowel(std::string_view s) {
	for (char c : s) if (!isVowel(c)) return boolean<char>(false, c);
	return boolean<char>(true);
}

constexpr boolean<char> isConsonant(std::string_view s) {
	for (char c : s) if (!isConsonant(c)) return boolean<char>(false, c);
	return boolean<char>(true);
}

namespace details {
	// Test two numbers for equality, accounting for +/-INF, NaN and precision.
	// Real expected is considered the reference value for relative error.
	bool floatEqual(Real given, Real expected, Real floatAbsTol, Real floatRelTol) {
		judgeAssert<std::domain_error>(floatAbsTol >= 0.0_real, "floatEqual(): floatAbsTol must be positive!");
		judgeAssert<std::domain_error>(floatRelTol >= 0.0_real, "floatEqual(): floatRelTol must be positive!");
		// Finite values are compared with some tolerance
		if (std::isfinite(given) and std::isfinite(expected)) {
			Real absDiff = std::abs(given-expected);
			Real relDiff = std::abs((given-expected)/expected);
			return absDiff <= floatAbsTol or relDiff <= floatRelTol;
		}
		// NaN is equal to NaN (-NaN is also equal NaN)
		if (std::isnan(given) and std::isnan(expected)) {
			return true;
		}
		// Infinite values are equal if their sign matches
		if (std::isinf(given) and std::isinf(expected)) {
			return std::signbit(given) == std::signbit(expected);
		}
		// Values in different classes are always different.
		return false;
	}

	constexpr boolean<std::size_t> stringEqual(std::string_view a, std::string_view b, bool caseSensitive) {
		std::size_t i = 0;
		for (; i < a.size() and i < b.size(); i++) {
			char aa = a[i];
			char bb = b[i];
			if (!caseSensitive) {
				aa = toDefaultCase(aa);
				bb = toDefaultCase(bb);
			}
			if (aa != bb) {
				return boolean<std::size_t>(false, i);
			}
		}
		if (a.size() != b.size()) {
			return boolean<std::size_t>(false, i);
		} else {
			return boolean<std::size_t>(true);
		}
	}

	constexpr bool isToken(std::string_view a) {
		if (a.empty()) return false;
		for (char c : a) {
			if (c == ' ') return false;
			if (c == '\n') return false;
			if (c == '\r') return false;
			if (c == '\t') return false;
			if (c == '\f') return false;
			if (c == '\v') return false;
		}
		return true;
	}

	template<typename T>
	bool parse(std::string_view s, T& res) {
		const char* begin = s.data();
		const char* end = s.data() + s.size();
		if (!s.empty() && s[0] == '+') begin++;
		auto [ptr, ec] = std::from_chars(begin, end, res);
		return ptr == end and ec == std::errc();
	}
	#ifdef DOUBLE_FALLBACK
	template<>
	bool parse(std::string_view s, Real& res) {
		try {
			std::size_t pos = 0;
			res = std::stold(std::string(s), &pos);
			return pos == s.size();
		} catch(...) {
			return false;
		}
	}
	#endif
	template<>
	bool parse(std::string_view s, std::string& res) {
		res = s;
		return true;
	}

}

boolean<Integer> isInteger(const std::string& s) {
	if (!std::regex_match(s, INTEGER_REGEX)) return boolean<Integer>(false);
	Integer value = 0;
	if (!details::parse<Integer>(s, value)) return boolean<Integer>(false);
	return boolean<Integer>(true, value);
}

boolean<Real> isReal(const std::string& s) {
	if (!std::regex_match(s, REAL_REGEX)) return boolean<Real>(false);
	Real value = 0;
	if (!details::parse<Real>(s, value)) return boolean<Real>(false);
	return boolean<Real>(true, value);
}

//============================================================================//
// args parser                                                                //
//============================================================================//
class ParameterBase {
	friend class Command;
	friend struct Parameter;

	std::optional<std::string_view> token;

	template<typename T>
	T parse(std::string_view s) const {
		T res = {};
		judgeAssert<std::invalid_argument>(details::parse<T>(s, res), "Command: Could not parse args");
		return res;
	}

	ParameterBase() = default;
	explicit ParameterBase(std::string_view token_) : token(token_) {}

public:
	std::string asString() const {
		return std::string(token.value());
	}

	std::string asString(std::string_view defaultValue) const {
		return std::string(token.value_or(defaultValue));
	}

	Integer asInteger() const {
		return parse<Integer>(token.value());
	}

	Integer asInteger(Integer defaultValue) const {
		return token ? asInteger() : defaultValue;
	}

	Real asReal() const {
		return parse<Real>(token.value());
	}

	Real asReal(Real defaultValue) const {
		return token ? asReal() : defaultValue;
	}
};

struct Parameter final : private ParameterBase {
	Parameter() = default;
	explicit Parameter(std::string_view token) : ParameterBase(token) {}

	using ParameterBase::asString;
	using ParameterBase::asInteger;
	using ParameterBase::asReal;

	bool exists() const {
		return token.has_value();
	}

	explicit operator bool() const {
		return exists();
	}
};

class Command final : private ParameterBase {
	const std::vector<std::string>& raw;
	const Integer first, count;
	const bool found;

	template<typename T, std::size_t... IS >
	auto asTuple(std::index_sequence<IS...> /**/) const {
		return std::make_tuple(parse<T>(raw[first + IS])...);
	}

	template<typename T, Integer N>
	auto as() const {
		if constexpr (N < 0) {
			std::vector<T> res;
			std::transform(raw.begin() + first,
			               raw.begin() + first + count,
			               std::back_inserter(res), [this](const std::string& value) {
				return parse<T>(value);
			});
			return res;
		} else {
			judgeAssert<std::invalid_argument>(N <= count, "Command: Could not parse args (too few args)");
			return asTuple<T>(std::make_index_sequence<static_cast<UInteger>(N)>{});
		}
	}
public:
	explicit Command(const std::vector<std::string>& raw_) : raw(raw_), first(0), count(0), found(false) {}
	explicit Command(const std::vector<std::string>& raw_, Integer first_, Integer count_)
	                 : ParameterBase(count_ == 0 ? ParameterBase() : ParameterBase(raw_[first_])),
	                   raw(raw_), first(first_), count(count_), found(true) {
		judgeAssert<std::invalid_argument>(count >= 0, "Command: Invalid command in args!");
	}

	bool exists() const {
		return found;
	}

	explicit operator bool() const {
		return exists();
	}

	Integer parameterCount() const {
		return count;
	}

	Parameter operator[](Integer i) const {
		if (i >= 0 and i < count) return Parameter(raw[first + i]);
		return Parameter();
	}

	using ParameterBase::asString;
	using ParameterBase::asInteger;
	using ParameterBase::asReal;

	template<Integer N = -1>
	auto asStrings() const {
		return as<std::string, N>();
	}

	template<Integer N = -1>
	auto asIntegers() const {
		return as<Integer, N>();
	}

	template<Integer N = -1>
	auto asReals() const {
		return as<Real, N>();
	}

};

class CommandParser final {
	std::vector<std::string> raw;
	std::map<std::string_view, std::pair<Integer, Integer>> commands;
	std::map<std::string_view, Integer> tokens;

	static bool isCommand(std::string_view s) {
		return s.size() > 2 and s.substr(0, 2) == COMMAND_PREFIX;
	}
	void addCommand(std::string_view command, Integer first, Integer count = 0) {
		judgeAssert<std::invalid_argument>(commands.count(command) == 0, "CommandParser: Duplicated command in args!");
		commands.emplace(command, std::pair<Integer, Integer>{first, count});
	}

public:
	CommandParser() = default;
	explicit CommandParser(int argc, char** argv) {
		raw.assign(argc, {});
		std::string_view command = EMPTY_COMMAND;
		Integer first = 0;
		Integer count = 0;
		for (int i = 0; i < argc; i++) {
			raw[i] = std::string(argv[i]);
			tokens.emplace(raw[i], i+1);
			if (isCommand(raw[i])) {
				addCommand(command, first, count);
				command = raw[i];
				first = i+1;
				count = 0;
			} else {
				count++;
			}
		}
		addCommand(command, first, count);
	}
	CommandParser(CommandParser&&) = default;
	CommandParser& operator=(CommandParser&&) = default;

	CommandParser(const CommandParser&) = delete;
	CommandParser& operator=(const CommandParser&) = delete;

	std::string_view operator[](Integer t) const {
		judgeAssert<std::out_of_range>(t >= 0 and t < static_cast<Integer>(raw.size()), "CommandParser: Index out of args!");
		return raw[t];
	}
	Command operator[](std::string_view command) const & {
		judgeAssert<std::invalid_argument>(details::isToken(command), "CommandParser: command must not contain a space!");
		auto it = commands.find(command);
		if (it == commands.end()) return Command(raw);
		return Command(raw, it->second.first, it->second.second);
	}
	Command getRaw(std::string_view command) const & {
		judgeAssert<std::invalid_argument>(details::isToken(command), "CommandParser: command must not contain a space!");
		auto it = tokens.find(command);
		if (it == tokens.end()) return Command(raw);
		return Command(raw, it->second, raw.size() - it->second);
	}
	Command getRaw() const & {
		return Command(raw, 0, raw.size());
	}
};


//============================================================================//
// Constants                                                                  //
//============================================================================//
Parameter parseConstant(std::string_view s) {
	if (s.size() >= 4 and
		s.substr(0, 2) == "{{" and
		s.substr(s.size() - 2) == "}}") {
		return Parameter();
	}
	return Parameter(s);
}

#define constant(key) parseConstant(#key)


//============================================================================//
// Constraints                                                                //
//============================================================================//
template<typename T>
class Bounds final {
	bool hadMin, hadMax;	// was value==lower/upper at some point
	T min, max;				// range of seen values
	T lower, upper;			// bounds for value
public:
	constexpr explicit Bounds(T lower_, T upper_, T value_) :
	                          hadMin(false), hadMax(false),
	                          min(value_), max(value_),
	                          lower(lower_), upper(upper_) {
		update(lower_, upper_, value_);
	}

	void update(T lower_, T upper_, T value_) {
		if constexpr (std::is_same_v<T, Real>) {
			hadMin |= details::floatEqual(value_, lower_, DEFAULT_EPS, DEFAULT_EPS);
			hadMax |= details::floatEqual(value_, upper_, DEFAULT_EPS, DEFAULT_EPS);
		} else {
			hadMin |= value_ == lower_;
			hadMax |= value_ == upper_;
		}
		min = std::min(min, value_);
		max = std::max(max, value_);
		lower = std::min(lower, lower_);
		upper = std::max(upper, upper_);
	}

	friend std::ostream& operator<<(std::ostream& os, const Bounds<T>& bounds) {
		os << bounds.hadMin << " " << bounds.hadMax << " ";
		os << bounds.min << " " << bounds.max << " ";
		return os << bounds.lower << " " << bounds.upper;
	}

};

namespace details {
	//using typeIndex = std::type_index;
	using typeIndex = void*;

	template<typename T>
	typeIndex getTypeIndex() {
		//return std::type_index(type id(T));
		static T* uniqueTypeIndex = nullptr;
		return &uniqueTypeIndex;
	}
}

class Constraint final {
	friend class ConstraintsLogger;
	std::variant<
		std::monostate,		// uninitialized
		Bounds<Integer>,	// Integer or container bound
		Bounds<Real>		// Real bound
	> bound;
	std::optional<details::typeIndex> type;

	template<typename T, typename X = T>
	void update(T lower, T upper, T value) {
		if constexpr(std::is_integral_v<T>) {
			upper--; // for BAPCtools the range is closed but we use half open ranges!
		}
		if (!type) {
			type = details::getTypeIndex<X>();
			bound = Bounds<T>(lower, upper, value);
		}
		judgeAssert<std::logic_error>(type == details::getTypeIndex<X>(), "Constraint: type must not change!");
		std::get<Bounds<T>>(bound).update(lower, upper, value);
	}
public:
	Constraint() = default;
	Constraint(Constraint&&) = default;
	Constraint& operator=(Constraint&&) = default;

	Constraint(const Constraint&) = delete;
	Constraint& operator=(const Constraint&) = delete;

	template<typename V, typename std::enable_if_t<std::is_integral_v<V>, bool> = true>
	void log(Integer lower, Integer upper, V value) {
		update<Integer>(lower, upper, value);
	}

	template<typename V, typename std::enable_if_t<std::is_floating_point_v<V>, bool> = true>
	void log(Real lower, Real upper, V value) {
		update<Real>(lower, upper, value);
	}

	template<typename C, typename std::enable_if_t<!std::is_arithmetic_v<C>, bool> = true>
	void log(Integer lower, Integer upper, const C& container) {
		update<Integer, C>(lower, upper, static_cast<Integer>(std::size(container)));
	}
};

class ConstraintsLogger final {
	std::optional<std::string> fileName;
	std::map<std::string, std::size_t> byName;
	std::vector<std::unique_ptr<Constraint>> constraints;
public:
	ConstraintsLogger() = default;
	explicit ConstraintsLogger(std::string_view fileName_) : fileName(fileName_) {}

	ConstraintsLogger(ConstraintsLogger&&) = default;
	ConstraintsLogger& operator=(ConstraintsLogger&&) = default;

	ConstraintsLogger(const ConstraintsLogger&) = delete;
	ConstraintsLogger& operator=(const ConstraintsLogger&) = delete;

	Constraint& operator[](const std::string& name) & {
		judgeAssert<std::invalid_argument>(details::isToken(name), "Constraint: name must not contain a space!");
		auto res = byName.try_emplace(name, constraints.size());
		if (res.second) constraints.emplace_back(std::make_unique<Constraint>());
		return *(constraints[res.first->second]);
	}

	void write() const {
		if (!fileName) return;
		std::ofstream os(*fileName);
		os << std::noboolalpha;
		os << std::fixed;
		os << std::setprecision(DEFAULT_PRECISION);
		std::vector<std::string_view> names(byName.size());
		for (const auto& [name, id] : byName) names[id] = name;
		for (std::size_t i = 0; i < names.size(); i++) {
			const Constraint& c = *(constraints[i]);
			if (c.type) {
				os << "LocationNotSupported:" << names[i] << " " << names[i] << " ";
				if (c.bound.index() == 1) os << std::get<1>(c.bound);
				if (c.bound.index() == 2) os << std::get<2>(c.bound);
				os << std::endl;
			}
		}
	}

	~ConstraintsLogger() noexcept {
		write();
	}
};

//============================================================================//
// custom input stream                                                        //
//============================================================================//
class InputStream final {
	std::unique_ptr<std::ifstream> managed;
	std::istream* in;
	bool spaceSensitive, caseSensitive;
	OutputStream* out;
	Verdicts::Verdict onFail;
	Real floatAbsTol;
	Real floatRelTol;

	void init() {
		if (spaceSensitive) *in >> std::noskipws;
		else *in >> std::skipws;
	}

	void checkIn() {
		judgeAssert<std::runtime_error>(in != nullptr, "InputStream: not initialized!");
	}

public:
	InputStream() = default;
	explicit InputStream(const std::filesystem::path& path,
	                     bool spaceSensitive_,
	                     bool caseSensitive_,
	                     OutputStream& out_,
	                     Verdicts::Verdict onFail_,
	                     Real floatAbsTol_ = DEFAULT_EPS,
	                     Real floatRelTol_ = DEFAULT_EPS) :
	                     managed(std::make_unique<std::ifstream>(path)),
	                     in(managed.get()),
	                     spaceSensitive(spaceSensitive_),
	                     caseSensitive(caseSensitive_),
	                     out(&out_),
	                     onFail(onFail_),
	                     floatAbsTol(floatAbsTol_),
	                     floatRelTol(floatRelTol_) {
		judgeAssert<std::runtime_error>(managed->good(), "InputStream: Could not open File: " + path.string());
		init();
	}
	explicit InputStream(std::istream& in_,
	                     bool spaceSensitive_,
	                     bool caseSensitive_,
	                     OutputStream& out_,
	                     Verdicts::Verdict onFail_,
	                     Real floatAbsTol_ = DEFAULT_EPS,
	                     Real floatRelTol_ = DEFAULT_EPS) :
	                     managed(),
	                     in(&in_),
	                     spaceSensitive(spaceSensitive_),
	                     caseSensitive(caseSensitive_),
	                     out(&out_),
	                     onFail(onFail_),
	                     floatAbsTol(floatAbsTol_),
	                     floatRelTol(floatRelTol_) {
		init();
	}

	InputStream(InputStream&& other) = default;
	InputStream& operator=(InputStream&& other) = default;

	InputStream(const InputStream&) = delete;
	InputStream& operator=(const InputStream&) = delete;

	void eof() {
		checkIn();
		if (!spaceSensitive) *in >> std::ws;
		if (in->peek() != std::char_traits<char>::eof()) {
			in->get();
			*out << "Missing EOF!";
			fail();
		}
	}

	void noteof() {
		checkIn();
		if (!spaceSensitive) *in >> std::ws;
		if (in->peek() == std::char_traits<char>::eof()) {
			*out << "Unexpected EOF!" << onFail;
		}
	}

	void space() {
		if (spaceSensitive) {
			noteof();
			if (in->get() != std::char_traits<char>::to_int_type(SPACE)) {
				*out << "Missing space!";
				fail();
			}
		}
	}

	void newline() {
		if (spaceSensitive) {
			noteof();
			if (in->get() != std::char_traits<char>::to_int_type(NEWLINE)) {
				*out << "Missing newline!";
				fail();
			}
		}
	}

private:
	void check(const std::string& token, const std::regex& pattern) {
		if (!std::regex_match(token, pattern)) {
			*out << "Token \"" << token << "\" does not match pattern!";
			fail();
		}
	}

	std::function<void()> checkSeparator(char separator) {
		if (separator == SPACE) return [this](){space();};
		if (separator == NEWLINE) return [this](){newline();};
		judgeAssert<std::invalid_argument>(false, "InputStream: Separator must be ' '  or '\\n'!");
		return {};
	}

	template<typename T>
	T parse(const std::string& s) {
		T res = {};
		if (!details::parse<T>(s, res)) {
			*out << "Could not parse token \"" << s << "\"!";
			fail();
		}
		return res;
	}

public:
	std::string string() {
		noteof();
		if (spaceSensitive and !std::isgraph(in->peek())) {
			in->get();
			*out << "Invalid whitespace!";
			fail();
		}
		std::string res;
		*in >> res;
		if (res.empty()) {
			*out << "Unexpected EOF!" << onFail;
		}
		if (!caseSensitive) toDefaultCase(res);
		return res;
	}

	std::string string(Integer lower, Integer upper) {
		std::string t = string();
		Integer length = static_cast<Integer>(t.size());
		if (length < lower or length >= upper) {
			*out << "String length " << length << " out of range [" << lower << ", " << upper << ")!";
			fail();
		}
		return t;
	}

	std::string string(Integer lower, Integer upper, Constraint& constraint) {
		std::string res = string(lower, upper);
		constraint.log(lower, upper, res);
		return res;
	}

	std::string string(const std::regex& pattern) {
		std::string t = string();
		check(t, pattern);
		return t;
	}

	std::string string(const std::regex& pattern, Integer lower, Integer upper) {
		std::string t = string(lower, upper);
		check(t, pattern);
		return t;
	}

	std::string string(const std::regex& pattern, Integer lower, Integer upper, Constraint& constraint) {
		std::string res = string(pattern, lower, upper);
		constraint.log(lower, upper, res);
		return res;
	}

	template<typename... Args>
	std::vector<std::string> strings(Args... args, Integer count, char separator) {
		auto sepCall = checkSeparator(separator);
		std::vector<std::string> res(count);
		for (std::size_t i = 0; i < res.size(); i++) {
			res[i] = string(args...);
			if (i + 1 < res.size()) sepCall();
		}
		return res;
	}

	std::vector<std::string> strings(Integer count, char separator = DEFAULT_SEPARATOR) {
		return strings<>(count, separator);
	}

	std::vector<std::string> strings(Integer lower, Integer upper,
	                                 Integer count, char separator = DEFAULT_SEPARATOR) {
		return strings<Integer, Integer>(lower, upper, count, separator);
	}

	std::vector<std::string> strings(Integer lower, Integer upper, Constraint& constraint,
	                                 Integer count, char separator = DEFAULT_SEPARATOR) {
		return strings<Integer, Integer, Constraint&>(lower, upper, constraint, count, separator);
	}

	std::vector<std::string> strings(const std::regex& pattern,
	                                 Integer count, char separator = DEFAULT_SEPARATOR) {
		return strings<const std::regex&>(pattern, count, separator);
	}

	std::vector<std::string> strings(const std::regex& pattern, Integer lower, Integer upper,
	                                 Integer count, char separator = DEFAULT_SEPARATOR) {
		return strings<const std::regex&, Integer, Integer>(pattern, lower, upper, count, separator);
	}

	std::vector<std::string> strings(const std::regex& pattern, Integer lower, Integer upper, Constraint& constraint,
	                                 Integer count, char separator = DEFAULT_SEPARATOR) {
		return strings<const std::regex&, Integer, Integer, Constraint&>(pattern, lower, upper, constraint, count, separator);
	}

	Integer integer() {
		return parse<Integer>(string(INTEGER_REGEX));
	}

	Integer integer(Integer lower, Integer upper) {
		Integer res = integer();
		if (res < lower or res >= upper) {
			*out << "Integer " << res << " out of range [" << lower << ", " << upper << ")!";
			fail();
		}
		return res;
	}

	Integer integer(Integer lower, Integer upper, Constraint& constraint) {
		Integer res = integer(lower, upper);
		constraint.log(lower, upper, res);
		return res;
	}

	template<typename... Args>
	std::vector<Integer> integers(Args... args, Integer count, char separator) {
		auto sepCall = checkSeparator(separator);
		std::vector<Integer> res(count);
		for (std::size_t i = 0; i < res.size(); i++) {
			res[i] = integer(args...);
			if (i + 1 < res.size()) sepCall();
		}
		return res;
	}

	std::vector<Integer> integers(Integer count, char separator = DEFAULT_SEPARATOR) {
		return integers<>(count, separator);
	}

	std::vector<Integer> integers(Integer lower, Integer upper,
	                              Integer count, char separator = DEFAULT_SEPARATOR) {
		return integers<Integer, Integer>(lower, upper, count, separator);
	}

	std::vector<Integer> integers(Integer lower, Integer upper, Constraint& constraint,
	                              Integer count, char separator = DEFAULT_SEPARATOR) {
		return integers<Integer, Integer, Constraint&>(lower, upper, constraint, count, separator);
	}

	// this does not allow NaN or Inf!
	// However, those should never be desired.
	Real real() {
		return parse<Real>(string(REAL_REGEX));
	}

	Real real(Real lower, Real upper) {// uses eps
		Real res = real();
		if (details::floatEqual(res, lower, floatAbsTol, floatRelTol)) return res;
		if (details::floatEqual(res, upper, floatAbsTol, floatRelTol)) return res;
		if (std::isnan(res) or !(res >= lower) or !(res < upper)) {
			*out << "Real " << res << " out of range [" << lower << ", " << upper << ")!";
			fail();
		}
		return res;
	}

	Real real(Real lower, Real upper, Constraint& constraint) {
		Real res = real(lower, upper);
		constraint.log(lower, upper, res);
		return res;
	}

	template<typename... Args>
	std::vector<Real> reals(Args... args, Integer count, char separator) {
		auto sepCall = checkSeparator(separator);
		std::vector<Real> res(count);
		for (std::size_t i = 0; i < res.size(); i++) {
			res[i] = real(args...);
			if (i + 1 < res.size()) sepCall();
		}
		return res;
	}

	std::vector<Real> reals(Integer count, char separator = DEFAULT_SEPARATOR) {
		return reals<>(count, separator);
	}

	std::vector<Real> reals(Real lower, Real upper,
	                        Integer count, char separator = DEFAULT_SEPARATOR) {
		return reals<Real, Real>(lower, upper, count, separator);
	}

	std::vector<Real> reals(Real lower, Real upper, Constraint& constraint,
	                        Integer count, char separator = DEFAULT_SEPARATOR) {
		return reals<Real, Real, Constraint&>(lower, upper, constraint, count, separator);
	}

	Real realStrict(Real lower, Real upper, Integer minDecimals, Integer maxDecimals) {// does not use eps
		std::string t = string(STRICT_REAL_REGEX);
		auto dot = t.find('.');
		Integer decimals = dot == std::string::npos ? 0 : t.size() - dot - 1;
		if (decimals < minDecimals or decimals >= maxDecimals) {
			*out << "Real " << t << " has wrong amount of decimals!";
			fail();
			return 0;
		}
		try {
			Real res = parse<Real>(t);
			if (std::isnan(res) or !(res >= lower) or !(res < upper)) {
				*out << "Real " << res << " out of range [" << lower << ", " << upper << ")!";
				fail();
			}
			return res;
		} catch(...) {
			*out << "Could not parse token \"" << t << "\" as real!";
			fail();
			return 0;
		}
	}

	Real realStrict(Real lower, Real upper, Integer minDecimals, Integer maxDecimals, Constraint& constraint) {
		Real res = realStrict(lower, upper, minDecimals, maxDecimals);
		constraint.log(lower, upper, res);
		return res;
	}

	template<typename... Args>
	std::vector<Real> realsStrict(Args... args, Integer count, char separator) {
		auto sepCall = checkSeparator(separator);
		std::vector<Real> res(count);
		for (std::size_t i = 0; i < res.size(); i++) {
			res[i] = realStrict(args...);
			if (i + 1 < res.size()) sepCall();
		}
		return res;
	}

	std::vector<Real> realsStrict(Real lower, Real upper, Integer minDecimals, Integer maxDecimals,
	                              Integer count, char separator = DEFAULT_SEPARATOR) {
		return realsStrict<Real, Real, Integer, Integer>(lower, upper, minDecimals, maxDecimals, count, separator);
	}

	std::vector<Real> realsStrict(Real lower, Real upper, Integer minDecimals, Integer maxDecimals, Constraint& constraint,
	                              Integer count, char separator = DEFAULT_SEPARATOR) {
		return realsStrict<Real, Real, Integer, Integer, Constraint&>(lower, upper, minDecimals, maxDecimals, constraint, count, separator);
	}

	void expectString(std::string_view expected) {
		judgeAssert<std::invalid_argument>(details::isToken(expected), "InputStream: expected must not contain a space!");
		std::string seen = string();
		auto [eq, pos] = details::stringEqual(seen, expected, caseSensitive);
		if (!eq) {
			auto format = [pos=pos,out=out](std::string_view s){
				Integer PREFIX = 10;
				Integer WINDOW = 5;
				if (s.size() <= PREFIX + WINDOW + TEXT_ELLIPSIS.size() * 2) {
					*out << s;
				} else if (*pos <= PREFIX + TEXT_ELLIPSIS.size() + WINDOW / 2 or *pos >= s.size()) {
					*out << s.substr(0, PREFIX + TEXT_ELLIPSIS.size() + WINDOW) << TEXT_ELLIPSIS;
				} else if (*pos + TEXT_ELLIPSIS.size() + WINDOW / 2 > s.size()) {
					*out << s.substr(0, PREFIX) << TEXT_ELLIPSIS << s.substr(*pos - WINDOW / 2);
				} else {
					*out << s.substr(0, PREFIX) << TEXT_ELLIPSIS << s.substr(*pos - WINDOW / 2, WINDOW) << TEXT_ELLIPSIS;
				}
			};
			*out << "Expected \"";
			format(expected);
			*out << "\" but got \"";
			format(seen);
			*out << "\"!";
			if (pos and *pos > 5) {
				*out << " (different at position: " << *pos+1 << ")";
			}
			fail();
		}
	}

	void expectInt(Integer expected) {
		Integer seen = integer();
		if (seen != expected) {
			*out << "Expected " << expected << " but got " << seen << "!";
			fail();
		}
	}

	void expectReal(Real expected) {
		Real seen = real();
		if (details::floatEqual(seen, expected, floatAbsTol, floatRelTol)) {
			*out << "Expected " << expected << " but got " << seen << "!";
			if (std::isfinite(seen) and std::isfinite(expected)) {
				Real absDiff = std::abs(seen-expected);
				Real relDiff = std::abs((seen-expected)/expected);
				*out << " (abs: " << absDiff << ", rel: " << relDiff << ")";
			}
			fail();
		}
	}
private:
	void fail() {
		//try to find input position...
		in->clear();
		auto originalPos = in->tellg();
		in->seekg(0);
		if (originalPos != std::streamoff(-1) and *in) {
			Integer line = 1;
			std::size_t l = 0, r = 0;
			std::string buffer;
			bool extend = true;
			while (*in and in->tellg() < originalPos) {
				l = r = buffer.size();
				if (std::isgraph(in->peek())) {
					std::string tmp;
					*in >> tmp;
					buffer += tmp;
				} else if (in->peek() == std::char_traits<char>::to_int_type(NEWLINE)) {
					line++;
					in->get();
					if (in->tellg() < originalPos) {
						buffer.clear();
					} else {
						buffer += ' ';
						extend = false;
					}
				} else {
					buffer += std::char_traits<char>::to_char_type(in->get());
				}
				if (*in and in->tellg() >= originalPos) {
					r = buffer.size();
				}
			}
			if (l != r) {
				*out << " Line: " << line << ", Char: " << l << '\n';
				if (extend) {
					char tmp;
					while ((buffer.size() < 80 or buffer.size() < r + 80) and in->get(tmp) and tmp != NEWLINE) {
						buffer += tmp;
					}
				}
				if (r > 60 and l > 20) {
					std::size_t offset = std::min(l - 20, r - 60);
					l -= offset;
					r -= offset;
					buffer = std::string(TEXT_ELLIPSIS) + buffer.substr(offset + TEXT_ELLIPSIS.size());
				}
				if (buffer.size() > 80) {
					buffer = buffer.substr(0, 80 - TEXT_ELLIPSIS.size());
					buffer += TEXT_ELLIPSIS;
					r = std::min(r, buffer.size());
				}
				*out << buffer << '\n';
				*out << std::string(l, ' ') << '^' << std::string(r - l - 1, '~');
			}
		}
		*out << onFail;
	}
};


//============================================================================//
// state guard                                                                //
//============================================================================//
namespace details {
	bool initialized(bool set = false) {
		static bool value = false;
		return std::exchange(value, value |= set);
	}

	struct InitGuard final {
		~InitGuard() {
			if (std::uncaught_exceptions() == 0) {
				judgeAssert<std::logic_error>(initialized(), "validate.h: init(argc, argv) was never called!");
			}
		}
	} initGuard;
}


//============================================================================//
// Settings                                                                   //
//============================================================================//
template<typename T>
class SettingBase {
	template<typename U>
	friend class Setting;
	friend class SettingCaseSensitive;

	T value;

	SettingBase(T value_) : value(value_) {}

public:
	SettingBase(SettingBase<T>&& other) = delete;
	SettingBase(const SettingBase<T>&) = delete;
	SettingBase<T>& operator=(SettingBase<T>&& other) = delete;
	SettingBase<T>& operator=(const SettingBase<T>&) = delete;

	operator T() const {
		return value;
	}

	SettingBase<T>& operator=(T value_) {
		judgeAssert<std::logic_error>(!details::initialized(), "validate.h: Cannot change setting after init(argc, argv) was called!");
		value = value_;
		return *this;
	}
};

template<typename T>
class Setting final : public SettingBase<T> {
public:
	Setting(T value_) : SettingBase<T>(value_) {}
	using SettingBase<T>::operator T;
	using SettingBase<T>::operator=;
};

class SettingCaseSensitive final : public SettingBase<bool> {
public:
	SettingCaseSensitive(bool value_) : SettingBase<bool>(value_) {}
	using SettingBase<bool>::operator bool;
	using SettingBase<bool>::operator=;

	std::regex regex(std::string_view s, std::regex_constants::syntax_option_type f = std::regex_constants::ECMAScript) const {
		if (!value) f |= std::regex_constants::icase;
		return std::regex(s.data(), s.size(), f);
	}
};


//============================================================================//
// Validators and stuff                                                       //
//============================================================================//
namespace ValidateBase {
	//OutputStream juryOut(std::cout); //already defined earlier
	//OutputStream juryErr(std::cerr);
	CommandParser arguments;
	//you may change these values before calling::init() but not afterwards!
	Setting<Real> floatAbsTol(DEFAULT_EPS);
	Setting<Real> floatRelTol(DEFAULT_EPS);
	Setting<bool> spaceSensitive(false);
	SettingCaseSensitive caseSensitive(false);

	// Real r2 is considered the reference value for relative error.
	bool floatEqual(Real given,
	                Real expected,
	                Real floatAbsTol_ = floatAbsTol,
	                Real floatRelTol_ = floatRelTol) {
		return details::floatEqual(given, expected, floatAbsTol_, floatRelTol_);
	}

	bool floatLess(Real given,
	               Real expected,
	               Real floatAbsTol_ = floatAbsTol,
	               Real floatRelTol_ = floatRelTol) {
		return given <= expected or floatEqual(given, expected, floatAbsTol_, floatRelTol_);
	}

	bool floatGreater(Real given,
	                  Real expected,
	                  Real floatAbsTol_ = floatAbsTol,
	                  Real floatRelTol_ = floatRelTol) {
		return given >= expected or floatEqual(given, expected, floatAbsTol_, floatRelTol_);
	}

	constexpr boolean<std::size_t> stringEqual(std::string_view a, std::string_view b, bool caseSensitive_ = caseSensitive) {
		return details::stringEqual(a, b, caseSensitive_);
	}

	namespace details {
		void init(int argc, char** argv) {
			judgeAssert<std::logic_error>(!::details::initialized(), "validate.h: init(argc, argv) was called twice!");

			//std::ios_base::sync_with_stdio(false);
			//cin.tie(nullptr);

			arguments = CommandParser(argc, argv);
			// parse default flags manually, since they dont use '--' prefix
			auto eps = arguments.getRaw(FLOAT_TOLERANCE);
			floatAbsTol = eps.asReal(floatAbsTol);
			floatRelTol = eps.asReal(floatRelTol);
			floatAbsTol = arguments.getRaw(FLOAT_ABSOLUTE_TOLERANCE).asReal(floatAbsTol);
			floatRelTol = arguments.getRaw(FLOAT_RELATIVE_TOLERANCE).asReal(floatRelTol);

			if (arguments.getRaw(SPACE_SENSITIVE)) spaceSensitive = true;
			if (arguments.getRaw(CASE_SENSITIVE)) caseSensitive = true;

			::details::initialized(true);
		}
	}

} // namespace ValidateBase

namespace ConstraintsBase {
	ConstraintsLogger constraint;

	void initConstraints() {
		if (auto file = ValidateBase::arguments[CONSTRAINT_COMMAND]) {
			constraint = ConstraintsLogger(file.asString());
		}
	}

} // namespace ConstraintsBase

//called as ./validator [arguments] < inputfile
namespace InputValidator {
	using namespace ValidateBase;
	using namespace ConstraintsBase;
	using namespace Verdicts;

	InputStream testIn;

	void init(int argc, char** argv) {
		spaceSensitive = true;
		caseSensitive = true;

		ValidateBase::details::init(argc, argv);
		juryOut = OutputStream(std::cout);

		testIn = InputStream(std::cin, spaceSensitive, caseSensitive, juryOut, Verdicts::WA, floatAbsTol, floatRelTol);
		initConstraints();
	}

} // namespace InputValidator

//called as ./validator input [arguments] < ansfile
namespace AnswerValidator {
	using namespace ValidateBase;
	using namespace ConstraintsBase;
	using namespace Verdicts;

	InputStream testIn;
	InputStream ans;

	void init(int argc, char** argv) {
		spaceSensitive = true;
		caseSensitive = true;

		ValidateBase::details::init(argc, argv);
		juryOut = OutputStream(std::cout);

		testIn = InputStream(std::filesystem::path(arguments[1]), false, caseSensitive, juryOut, Verdicts::FAIL);
		ans = InputStream(std::cin, spaceSensitive, caseSensitive, juryOut, Verdicts::WA);
		initConstraints();
	}

} // namespace AnswerValidator

//called as ./validator input judgeanswer feedbackdir [arguments] < teamoutput
namespace OutputValidator {
	using namespace ValidateBase;
	using namespace ConstraintsBase;
	using namespace Verdicts;

	InputStream testIn;
	InputStream juryAns;
	InputStream teamAns;
	OutputStream teamOut;

	void init(int argc, char** argv) {
		ValidateBase::details::init(argc, argv);
		juryOut = OutputStream(std::filesystem::path(arguments[3]) / JUDGE_MESSAGE, MESSAGE_MODE);
		teamOut = OutputStream(std::filesystem::path(arguments[3]) / TEAM_MESSAGE, MESSAGE_MODE);

		testIn = InputStream(std::filesystem::path(arguments[1]), false, caseSensitive, juryOut, Verdicts::FAIL);
		juryAns = InputStream(std::filesystem::path(arguments[2]), false, caseSensitive, juryOut, Verdicts::FAIL);
		teamAns = InputStream(std::cin, spaceSensitive, caseSensitive, juryOut, Verdicts::WA);
		initConstraints();
	}

} // namespace OutputValidator

//called as ./interactor input judgeanswer feedbackdir <> teamoutput
namespace Interactor {
	using namespace ValidateBase;
	using namespace Verdicts;

	OutputStream toTeam;
	InputStream testIn;
	InputStream fromTeam;
	OutputStream teamOut;

	void init(int argc, char** argv) {
		ValidateBase::details::init(argc, argv);
		juryOut = OutputStream(std::filesystem::path(arguments[3]) / JUDGE_MESSAGE, MESSAGE_MODE);
		teamOut = OutputStream(std::filesystem::path(arguments[3]) / TEAM_MESSAGE, MESSAGE_MODE);
		toTeam = OutputStream(std::cout);

		testIn = InputStream(std::filesystem::path(arguments[1]), false, caseSensitive, juryOut, Verdicts::FAIL);
		fromTeam = InputStream(std::cin, spaceSensitive, caseSensitive, juryOut, Verdicts::WA);
	}

} // namespace Interactor

//for called see OutputValidator or Interactor respectively
namespace Multipass {
	using namespace ValidateBase;

	namespace details {
		std::ostringstream nextpassBuffer;
	}
	Integer pass;
	InputStream prevstate;
	OutputStream nextstate;
	OutputStream nextpass;

	void init() {
		judgeAssert<std::logic_error>(::details::initialized(), "validate.h: Multipass::init() was called before init(argc, argv)!");

		auto path = std::filesystem::path(arguments[3]) / ".pass";
		std::string nextfile = ".state0";
		std::string prevfile = ".state1";
		if (std::filesystem::exists(path)) {
			std::ifstream in(path);
			in >> pass;
			pass++;
			if ((pass & 1) != 0) {
				std::swap(nextfile, prevfile);
			}
			prevstate = InputStream(std::filesystem::path(arguments[3]) / prevfile, false, true, juryOut, Verdicts::FAIL);
		} else {
			pass = 0;
		}
		std::filesystem::remove(std::filesystem::path(arguments[3]) / nextfile);
		nextstate = OutputStream(std::filesystem::path(arguments[3]) / nextfile, std::ios::out);
		nextpass = OutputStream(details::nextpassBuffer);
		std::ofstream out(path);
		out << pass;
	}

	[[noreturn]] void NEXT() {
		{
			std::ofstream file(std::filesystem::path(arguments[3]) / "nextpass.in");
			judgeAssert<std::runtime_error>(file.good(), "NEXT(): Could not open file: nextpass.in");
			file << details::nextpassBuffer.str();
		}
		exitVerdict(Verdicts::AC);
	}
	[[noreturn]] std::ostream& NEXT(std::ostream& os) {
		os << std::endl;
		NEXT();
	}

} // namespace Multipass

//called as ./generator [arguments]
namespace Generator {
	using namespace ValidateBase;
	using Verdicts::FAIL;

	OutputStream testOut;

	void init(int argc, char** argv) {
		ValidateBase::details::init(argc, argv);
		juryOut = OutputStream(std::cerr);
		testOut = OutputStream(std::cout);
	}

} // namespace Generator

#endif
