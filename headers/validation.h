#pragma once
// A header library to safely parse team input.
// It does not support floating points or big integers.
// Author: Ragnar Groot Koerkamp

// The easiest way to use this is to symlink it from a validator directory,
// so that it will be picked up when creating a contest zip.

// The default checking behaviour is lenient for both white space and case.
// When validating .in and .ans files, the case_sensitive and
// space_change_sensitive flags should be passed. When validating team output,
// the flags in problem.yaml should be used.

#include <algorithm>
#include <array>
#include <bitset>
#include <cassert>
#include <charconv>
#include <cstring>
#include <fstream>
#include <functional>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <optional>
#include <random>
#include <set>
#include <stdexcept>
#include <string>
#include <string_view>
#include <type_traits>
#include <unordered_map>
#include <utility>
#include <variant>
#include <vector>

const std::string_view case_sensitive_flag       = "case_sensitive";
const std::string_view ws_sensitive_flag         = "space_change_sensitive";
const std::string_view constraints_file_flag     = "--constraints_file";
const std::string_view generate_flag             = "--generate";
const std::string_view generate_binary_substring = "generat";

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
inline struct IncreasingTag : ArbitraryTag {
	static constexpr bool increasing = true;
} Increasing;
inline struct DecreasingTag : ArbitraryTag {
	static constexpr bool decreasing = true;
} Decreasing;
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

// this contains some specific code which emulates c++20 features
namespace cpp20 {

constexpr int countl_zero(unsigned long long x) {
	int res = 64;
	for(int i = 32; i > 0; i >>= 1) {
		if((x >> i) > 0) {
			res -= i;
			x >>= i;
		}
	}
	if(x > 0) res--;
	return res;
}

int popcount(unsigned long long x) {
	return static_cast<int>(std::bitset<64>(x).count());
}

constexpr long double PI = 3.141592653589793238462643383279502884l;

} // namespace cpp20

namespace Random {

constexpr unsigned int default_seed = 3141592653; // some digits of PI

unsigned long long bits64(std::mt19937_64& rng) {
	static_assert(std::mt19937_64::max() == 0xFFFF'FFFF'FFFF'FFFFull);
	static_assert(std::mt19937_64::min() == 0ull);
	return rng();
}

// generates a uniform real in [0, 1)
long double real64(std::mt19937_64& rng) {
	// a long double can represent more than 2^64 values in the range [0, 1)...
	// another problem is that real64() < 1.0/3.0 is technically biased.
	long double res = bits64(rng) / 0x1.0p64l;
	res += bits64(rng) / 0x1.0p128l;
	assert(res < 1.0l);
	return res;
}

bool bit(std::mt19937_64& rng) {
	return cpp20::popcount(bits64(rng)) & 1;
}

} // namespace Random

template <typename T>
constexpr bool is_number_v = std::is_same_v<T, long long> or std::is_same_v<T, long double>;

namespace Generators {

template <typename T>
struct ConstGenerator {
	static_assert(is_number_v<T> or std::is_same_v<T, char> or std::is_same_v<T, std::string>);
	static constexpr std::string_view name = "const";
	using Args                             = std::tuple<T>;

	const T const_;

	explicit ConstGenerator(T val) : const_(std::move(val)) {}

	// For char and string, the constant store has a different type than the min and max length
	// passed in.
	template <typename U>
	T operator()(U low, U high, std::mt19937_64& rng) const {
		return std::clamp(const_, low, high);
	}
};

struct MinGenerator {
	static constexpr std::string_view name = "min";
	using Args                             = std::tuple<>;

	explicit MinGenerator() = default;

	template <typename T>
	T operator()(T low, T high, std::mt19937_64& rng) const {
		static_assert(is_number_v<T>);
		return low;
	}
};

struct MaxGenerator {
	static constexpr std::string_view name = "max";
	using Args                             = std::tuple<>;

	explicit MaxGenerator() = default;

	template <typename T>
	T operator()(T low, T high, std::mt19937_64& rng) const {
		static_assert(is_number_v<T>);
		return high;
	}
};

struct UniformGenerator {
	static constexpr std::string_view name = "uniform";
	using Args                             = std::tuple<>;

	explicit UniformGenerator() = default;

	template <typename T>
	T operator()(T low, T high, std::mt19937_64& rng) const {
		static_assert(is_number_v<T>);
		if(low == high) return low;

		if constexpr(std::is_same_v<T, long long>) {
			assert(low < high);
			// Since C++20 we can assume Two's Complement but any sane system used it before anyway.
			// Rejection sampling is not as fast as possible but definitely unbiased.
			auto ul    = static_cast<unsigned long long>(low);
			auto uh    = static_cast<unsigned long long>(high);
			int shitfs = cpp20::countl_zero(uh - ul);
			unsigned long long res;
			do {
				res = Random::bits64(rng) >> shitfs;
			} while(res > uh - ul);
			return static_cast<long long>(res + ul);
		} else {
			assert(low < high);
			return low + Random::real64(rng) * (high - low);
		}
	}
};

template <typename T>
struct RangeGenerator {
	static_assert(is_number_v<T>);
	static constexpr std::string_view name = "range";
	using Args                             = std::tuple<T, T>;

	const T low_, high_;

	explicit RangeGenerator(T low, T high) : low_(low), high_(high) {}

	T operator()(T low, T high, std::mt19937_64& rng) const {
		return UniformGenerator()(std::max(low, low_), std::min(high, high_), rng);
	}
};

template <typename T>
struct StepRangeGenerator {
	static_assert(is_number_v<T>);
	static constexpr std::string_view name = "steprange";
	using Args                             = std::tuple<T, T, T>;

	const T low_, high_, step_;

	explicit StepRangeGenerator(T low, T high, T step) : low_(low), high_(high), step_(step) {}

	T operator()(T low, T high, std::mt19937_64& rng) const {
		// round up low to the first multiple of step_.
		T start;
		if(low <= low_) {
			start = low_;
		} else {
			// first multiple of low_+k*step_ >= low
			start = low_ + (long long)((low - low_) / step_) * step_;
			if(start < low) start += step_;
			assert(low <= start && start < low + step_);
		}
		long long maxsteps = (std::min(high, high_) - start) / step_;
		long long steps    = UniformGenerator()(0ll, maxsteps, rng);
		return start + steps * step_;
	}
};

struct NormalDistributionGenerator {
	static constexpr std::string_view name = "normal";
	using T                                = long double;
	using Args                             = std::tuple<T, T>;

	const T mean_, stddev_;

	explicit NormalDistributionGenerator(T mean, T stddev) : mean_(mean), stddev_(stddev) {
		assert(stddev_ >= 0);
	}

	// NOTE: Currently this retries instead of clamping to the interval.
	T operator()(T low, T high, std::mt19937_64& rng) const {
		assert(low < high);
		T v;
		while(true) {
			T u1 = Random::real64(rng);
			T u2 = Random::real64(rng);
			// Box-Muller-Methode
			// https://en.wikipedia.org/wiki/Box%E2%80%93Muller_transform
			v = std::sqrt(-2.0l * std::log(u1)) * std::cos(2.0l * cpp20::PI * u2);
			v = std::sqrt(stddev_) * v + mean_;
			if(v >= low && v < high) return v;
			v = std::sqrt(-2.0l * std::log(u1)) * std::sin(2.0l * cpp20::PI * u2);
			v = std::sqrt(stddev_) * v + mean_;
			if(v >= low && v < high) return v;
		}
		return v;
	}
};

struct ExponentialDistributionGenerator {
	static constexpr std::string_view name = "exponential";
	using T                                = long double;
	using Args                             = std::tuple<T>;

	T lambda_;

	explicit ExponentialDistributionGenerator(T lambda) : lambda_(lambda) { assert(lambda_ > 0); }

	// NOTE: Currently this retries instead of clamping to the interval.
	T operator()(T low, T high, std::mt19937_64& rng) const {
		assert(low < high);
		T v;
		while(true) {
			v = low - std::log(Random::real64(rng)) / lambda_;
			if(v < high) return v;
		}
	}
};

struct GeometricDistributionGenerator {
	static constexpr std::string_view name = "geometric";
	using T                                = long long;
	using Args                             = std::tuple<long double>;

	double p_;

	explicit GeometricDistributionGenerator(double p) : p_(p) {
		assert(p_ > 0);
		assert(p_ < 1);
	}

	// NOTE: Currently this retries instead of clamping to the interval.
	T operator()(T low, T high, std::mt19937_64& rng) const {
		assert(low <= high);
		T v;
		while(true) {
			// https://en.wikipedia.org/wiki/Geometric_distribution
			// "The exponential distribution is the continuous analogue of the geometric
			// distribution[...]"
			v = low + std::floor(std::log(Random::real64(rng)) / std::log1p(-p_));
			if(v <= high) return v;
		}
	}
};

struct BinomialDistributionGenerator {
	static constexpr std::string_view name = "binomial";
	using T                                = long long;
	using Args                             = std::tuple<long long, long double>;

	long long n_;
	double p_;

	explicit BinomialDistributionGenerator(long long n, double p) : n_(n), p_(p) {
		assert(p_ >= 0);
		assert(p_ <= 1);
		std::cerr << "Warning: Large n (" << n_ << ") is slow for BinomialDistributionGenerator!"
		          << std::endl;
	}

	// NOTE: Currently this retries instead of clamping to the interval.
	T operator()(T low, T high, std::mt19937_64& rng) const {
		assert(low <= high);
		// this will be slow for large n
		// (a faster implementation requires efficient poisson sampling)
		while(true) {
			T v = 0;
			for(long long i = 0; i < n_; i++) {
				v += Random::real64(rng) < p_ ? 1 : 0;
			}
			if(v >= low && v <= high) return v;
		}
	}
};

template <typename T>
struct ChoiceGenerator {
	using GeneratorType = std::conditional_t<
	    std::is_same_v<T, long long>,
	    std::variant<ConstGenerator<T>, MinGenerator, MaxGenerator, UniformGenerator,
	                 RangeGenerator<T>, StepRangeGenerator<T>, GeometricDistributionGenerator,
	                 BinomialDistributionGenerator>,
	    std::variant<ConstGenerator<T>, MinGenerator, MaxGenerator, UniformGenerator,
	                 RangeGenerator<T>, StepRangeGenerator<T>, NormalDistributionGenerator,
	                 ExponentialDistributionGenerator>>;

	std::vector<std::pair<GeneratorType, double>> generators_;
	double total_weight_;

	template <typename>
	struct Pack {};

	template <typename A>
	static A parse_number(std::string_view s) {
		static_assert(is_number_v<A>);
		if constexpr(std::is_same_v<A, long long>)
			return stoll(std::string(s));
		else
			return stold(std::string(s));
	}

	template <typename A>
	static A parse_argument(std::string_view& s) {
		auto end = s.find_first_of(",)");
		assert(end != std::string_view::npos);
		auto v = parse_number<A>(s.substr(0, end));
		s.remove_prefix(end);
		// Pop the trailing , or )
		s.remove_prefix(1);
		return v;
	}

	template <typename... As>
	static std::tuple<As...> parse_arguments(std::string_view& s,
	                                         Pack<std::tuple<As...>> /*unused*/) {
		std::tuple<As...> args{parse_argument<As>(s)...};
		return args;
	}

	// Try parsing one generator type from the start of s.
	template <typename G>
	static void parse_generator(std::string_view& s, std::optional<GeneratorType>& out) {
		if(out) return;
		if(s.substr(0, G::name.size()) != G::name) return;

		// Drop the name.
		s.remove_prefix(G::name.size());
		if constexpr(std::tuple_size_v<typename G::Args> == 0) {
			out.emplace(std::in_place_type_t<G>{});
			return;
		}

		// Drop the (
		assert(not s.empty() and s.front() == '(');
		s.remove_prefix(1);

		auto args = parse_arguments(s, Pack<typename G::Args>{});
		// Construct the resulting generator in-place in the variant..
		std::apply([&](const auto&... _args) { out.emplace(std::in_place_type_t<G>{}, _args...); },
		           args);
	}

	template <typename... Gs>
	static std::optional<GeneratorType> parse_generators(std::string_view& s,
	                                                     Pack<std::variant<Gs...>> /*unused*/) {
		std::optional<GeneratorType> out;
		(parse_generator<Gs>(s, out), ...);
		return out;
	}

	explicit ChoiceGenerator(std::string_view s) : total_weight_(0) {
		// PARSE
		while(not s.empty()) {
			auto generator = parse_generators(s, Pack<GeneratorType>{});
			if(!generator) {
				// Check for range syntax:
				auto comma = s.find_first_of(",:");
				if(comma == std::string::npos) comma = s.size();
				auto dots = s.find("..");
				if(dots != std::string_view::npos and dots < comma) {
					auto start = s.substr(0, dots);
					auto end   = s.substr(dots + 2, comma - dots - 2);

					generator.emplace(std::in_place_type_t<RangeGenerator<T>>{},
					                  parse_number<T>(start), parse_number<T>(end));
					s.remove_prefix(comma);
				}

				// Fall back to constant.
				if(!generator) {
					generator.emplace(std::in_place_type_t<ConstGenerator<T>>{},
					                  parse_number<T>(s.substr(0, comma)));
					s.remove_prefix(comma);
				}
			}

			// Parse weight if given.
			double weight = 1;
			if(not s.empty() and s.front() == ':') {
				s.remove_prefix(1);
				auto comma = s.find(',');
				if(comma == std::string_view::npos) comma = s.size();
				weight = parse_number<long double>(s.substr(0, comma));
				s.remove_prefix(comma);
			}

			// should now be at , or end
			assert(s.empty() or s.front() == ',');
			if(not s.empty()) s.remove_prefix(1);
			generators_.emplace_back(std::move(*generator), weight);
			total_weight_ += weight;
		}
	}

	T operator()(T low, T high, std::mt19937_64& rng) const {
		Generators::UniformGenerator uniform;
		double x = uniform.operator()<long double>(0, total_weight_, rng);
		for(size_t i = 0; i < generators_.size(); ++i) {
			x -= generators_[i].second;
			if(x <= 0)
				return std::visit([&](auto& g) { return g(low, high, rng); }, generators_[i].first);
		}
		assert(false);
	}
};

struct ParamGenerator {
	std::variant<std::string_view, ChoiceGenerator<long long>, ChoiceGenerator<long double>>
	    generator;
	explicit ParamGenerator(std::string_view s) : generator(s) {}

	template <typename T>
	T operator()(T low, T high, std::mt19937_64& rng) {
		static_assert(is_number_v<T>);
		if(std::holds_alternative<std::string_view>(generator)) {
			generator = ChoiceGenerator<T>(std::get<std::string_view>(generator));
		}
		return std::get<ChoiceGenerator<T>>(generator)(low, high, rng);
	}
};

} // namespace Generators

using Generators::ParamGenerator;

namespace Random {
template <class RandomIt>
void shuffle(RandomIt first, RandomIt last, std::mt19937_64& rng) {
	Generators::UniformGenerator uniform;
	long long n = last - first;
	for(long long i = n - 1; i > 0; i--) {
		std::swap(first[i], first[uniform(0ll, i, rng)]);
	}
}

template <class T>
void shuffle(std::pair<T, T>& in, std::mt19937_64& rng) {
	if(bit(rng)) std::swap(in.first, in.second);
}

template <class RandomIt>
auto& select(RandomIt first, RandomIt last, std::mt19937_64& rng) {
	assert(first != last);
	Generators::UniformGenerator uniform;
	long long n = last - first;
	return first[uniform(0ll, n - 1, rng)];
}

template <class T>
const T& select(const std::pair<T, T>& in, std::mt19937_64& rng) {
	return bit(rng) ? in.first : in.second;
}

template <class T>
T& select(std::pair<T, T>& in, std::mt19937_64& rng) {
	return bit(rng) ? in.first : in.second;
}

} // namespace Random

class Validator {
  protected:
	Validator(bool ws_, bool case_, std::istream& in_, std::string constraints_file_path_ = "",
	          std::optional<unsigned int> seed                        = std::nullopt,
	          std::unordered_map<std::string, ParamGenerator> params_ = {})
	    : in(in_), ws(ws_), case_sensitive(case_),
	      constraints_file_path(std::move(constraints_file_path_)), gen(seed.has_value()),
	      rng(seed.value_or(Random::default_seed)), params(std::move(params_)) {

		std::ios_base::sync_with_stdio(false);
		in.tie(nullptr);

		if(gen) return;
		if(ws)
			in >> std::noskipws;
		else
			in >> std::skipws;
	}

  public:
	// No copying, no moving.
	Validator(const Validator&)      = delete;
	Validator(Validator&&)           = delete;
	void operator=(const Validator&) = delete;
	void operator=(Validator&&)      = delete;

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
		static std::unordered_map<std::string, std::set<T>> seen;
		return seen;
	}
	template <typename T>
	auto& last_seen() {
		static std::unordered_map<std::string, T> last_seen;
		return last_seen;
	}
	template <typename T>
	auto& integers_seen() {
		static std::unordered_map<std::string, std::tuple<std::set<T>, std::vector<T>, bool>>
		    integers_seen;
		return integers_seen;
	}
	template <typename T>
	void reset(std::string name) {
		seen<T>().erase(name);
		last_seen<T>().erase(name);
		integers_seen<T>().erase(name);
	}

	template <typename T, typename Tag>
	void check_number(const std::string& name, T low, T high, T v, Tag /*unused*/) {
		static_assert(is_number_v<T>);
		if(v < low or v > high) {
			std::string type_name;
			if constexpr(std::is_integral_v<T>) {
				type_name = "integer";
			}
			if constexpr(std::is_floating_point_v<T>) {
				type_name = "float";
			}
			expected(name + ": " + type_name + " between " + std::to_string(low) + " and " +
			             std::to_string(high),
			         std::to_string(v));
		}
		log_constraint(name, low, high, v);
		if constexpr(Tag::unique) {
			auto [it, inserted] = seen<T>()[name].emplace(v);
			check(inserted, name, ": Value ", v, " seen twice, but must be unique!");
		} else {
			auto [it, inserted] = last_seen<T>().emplace(name, v);
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
	                  Tag /*unused*/) {
		using T = std::string;
		if((int)v.size() < low or (int) v.size() > high) {
			expected(name + ": " + "string with" + " length between " + std::to_string(low) +
			             " and " + std::to_string(high),
			         v);
		}
		log_constraint("|" + name + "|", low, high, static_cast<int>(v.size()));
		if constexpr(Tag::unique) {
			auto [it, inserted] = seen<T>()[name].emplace(v);
			check(inserted, name, ": Value ", v, " seen twice, but must be unique!");
		} else if(Tag::increasing or Tag::decreasing) {
			auto [it, inserted] = last_seen<T>().emplace(name, v);
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

	// Generate a random integer in [low, high] or float in [low, high).
	template <typename T>
	T uniform_number(T low, T high) {
		assert(low <= high);
		Generators::UniformGenerator uniform;
		if constexpr(std::is_integral<T>::value)
			return uniform.operator()<long long>(low, high, rng);
		else
			return uniform.operator()<long double>(low, high, rng);
	}

	template <typename T, typename Tag>
	T gen_number(const std::string& name, T low, T high, Tag /*unused*/) {
		static_assert(is_number_v<T>);
		T v;

		if constexpr(Tag::unique) {
			assert(params.find(name) == params.end() &&
			       "Parameters are not supported for unique values.");
			if constexpr(std::is_integral<T>::value) {
				auto& [seen_here, remaining_here, use_remaining] = integers_seen<T>()[name];

				if(use_remaining) {
					check(!remaining_here.empty(), name, ": no unique values left");
					v = remaining_here.back();
					remaining_here.pop_back();
				} else {
					do {
						v = uniform_number(low, high);
					} while(!seen_here.insert(v).second);

					struct CountIterator {
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
				auto& seen_here = seen<T>()[name];
				do {
					v = uniform_number(low, high);
				} while(!seen_here.insert(v).second);
			}

		} else {
			assert(not Tag::increasing && "Generating increasing sequences is not yet supported!");
			assert(not Tag::decreasing && "Generating decreasing sequences is not yet supported!");
			assert((std::is_same<Tag, ArbitraryTag>::value) &&
			       "Only Unique and Arbitrary are supported!");

			if(params.find(name) != params.end()) {
				v = params.at(name).operator()<T>(low, high, rng);
				// This will be checked during input validation of the generated case.
				// assert(low <= v and v <= high);
			} else {
				v = uniform_number<T>(low, high);
			}
		}

		return v;
	}

	std::string gen_string(const std::string& name, long long low, long long high,
	                       std::string_view chars) {
		assert(!chars.empty());

		int len;
		if(params.find(name + ".length") != params.end())
			len = params.at(name + ".length").operator()<long long>(low, high, rng);
		else
			len = uniform_number(low, high);
		std::string s(len, ' ');
		for(auto& x : s) x = chars[uniform_number<int>(0, chars.size() - 1)];

		out << s;
		return s;
	}

  public:
	template <typename Tag = ArbitraryTag>
	long long gen_integer(const std::string& name, long long low, long long high, Tag tag = Tag{}) {
		return gen_number(name, low, high, tag);
	}

	template <typename Tag = ArbitraryTag>
	long double gen_float(const std::string& name, long double low, long double high,
	                      Tag tag = Tag{}) {
		return gen_number(name, low, high, tag);
	}

  private:
	template <typename T, typename Tag>
	std::vector<T> gen_numbers(const std::string& name, int count, T low, T high, Tag /*unused*/) {
		static_assert(is_number_v<T>);
		std::vector<T> v;
		v.reserve(count);
		if constexpr(std::is_same_v<Tag, ArbitraryTag>) {
			if(params.find(name) != params.end()) {
				auto& generator = params.at(name);
				for(int i = 0; i < count; ++i) {
					auto val = generator.operator()<T>(low, high, rng);
					assert(low <= val and val <= high);
					v.push_back(val);
				}
			} else {
				for(int i = 0; i < count; ++i) {
					v.push_back(uniform_number<T>(low, high));
				}
			}
		} else if constexpr(Tag::unique) {
			assert(params.find(name) == params.end() &&
			       "Parameters are not supported for unique values.");
			std::set<T> seen_here;
			if constexpr(std::is_integral_v<T>) {
				if(2 * count < high - low) {
					for(int i = 0; i < count; ++i) {
						// If density < 1/2: retry.
						T w;
						do {
							w = uniform_number(low, high);
						} while(!seen_here.insert(w).second);
						v.push_back(w);
					}
				} else {
					// If density >= 1/2, crop a random permutation.
					v.resize(high - low + 1);
					iota(begin(v), end(v), low);
					Random::shuffle(begin(v), end(v), rng);
					v.resize(count);
				}
			} else {
				for(int i = 0; i < count; ++i) {
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
			if(integral_strict) {
				assert(params.find(name) == params.end() &&
				       "Parameters are not supported for strict integer values.");
				high = high - count + 1;
			}

			if(params.find(name) != params.end()) {
				auto& generator = params.at(name);
				for(int i = 0; i < count; ++i) {
					auto val = generator.operator()<T>(low, high, rng);
					assert(low <= val and val <= high);
					v.push_back(val);
				}
			} else {
				for(int i = 0; i < count; ++i) {
					v.push_back(uniform_number<T>(low, high));
				}
			}

			sort(begin(v), end(v));

			if(integral_strict) {
				for(int i = 0; i < count; ++i) v[i] += i;
			}

			if(Tag::decreasing) reverse(begin(v), end(v));
		}

		return v;
	}

  public:
	template <typename Tag = ArbitraryTag>
	std::vector<long long> gen_integers(const std::string& name, int count, long long low,
	                                    long long high, Tag tag = Tag{}) {
		return gen_numbers(name, count, low, high, tag);
	}

	template <typename Tag = ArbitraryTag>
	std::vector<long double> gen_floats(const std::string& name, int count, long double low,
	                                    long double high, Tag tag = Tag{}) {
		return gen_numbers(name, count, low, high, tag);
	}

  private:
	template <typename T, typename Tag>
	T read_number(const std::string& name, T low, T high, Tag tag) {
		if(gen) {
			auto v = gen_number(name, low, high, tag);
			out << std::setprecision(10) << std::fixed << v;
			return v;
		}

		const auto v = [&] {
			if constexpr(std::is_integral<T>::value)
				return read_integer(name);
			else
				return read_float(name);
		}();

		check_number(name, low, high, v, tag);
		return v;
	}

	// Read a vector of numbers, separated by spaces and ended by a newline.
	template <typename T, typename Tag>
	std::vector<T> read_numbers(const std::string& name, int count, T low, T high, Tag tag,
	                            Separator sep) {
		if(gen) {
			auto v = gen_numbers(name, count, low, high, tag);

			out << std::setprecision(10) << std::fixed;
			for(int i = 0; i < count; ++i) {
				out << v[i];
				if(i < count - 1) separator(sep);
			}
			newline();

			return v;
		}
		reset<T>(name);
		std::vector<T> v(count);
		for(int i = 0; i < count; ++i) {
			if constexpr(std::is_integral<T>::value)
				v[i] = read_integer(name);
			else
				v[i] = read_float(name);
			check_number(name, low, high, v[i], tag);
			if(i < count - 1) separator(sep);
		}
		newline();
		return v;
	}

  public:
	template <typename Tag = ArbitraryTag>
	long long read_integer(const std::string& name, long long low, long long high,
	                       Tag tag = Tag{}) {
		return read_number(name, low, high, tag);
	}
	template <typename Tag = ArbitraryTag>
	std::vector<long long> read_integers(const std::string& name, int count, long long low,
	                                     long long high, Tag tag = Tag{}, Separator sep = Space) {
		return read_numbers(name, count, low, high, tag, sep);
	}

	template <typename Tag = ArbitraryTag>
	long double read_float(const std::string& name, long double low, long double high,
	                       Tag tag = Tag{}) {
		return read_number(name, low, high, tag);
	}
	template <typename Tag = ArbitraryTag>
	std::vector<long double> read_floats(const std::string& name, int count, long double low,
	                                     long double high, Tag tag = Tag{}, Separator sep = Space) {
		return read_numbers(name, count, low, high, tag, sep);
	}

	// Read a vector of strings, separated by spaces and ended by a newline.
	template <typename Tag = ArbitraryTag>
	std::vector<std::string> read_strings(const std::string& name, int count, int min, int max,
	                                      const std::string_view chars = "", Tag tag = Tag(),
	                                      Separator sep = Space) {
		reset<std::string>(name);
		if(gen) return gen_strings(name, count, min, max, chars, tag, sep);
		assert(!gen);
		std::vector<std::string> v(count);
		for(int i = 0; i < count; ++i) {
			v[i] = read_string(name, min, max, chars, tag);
			if(i < count - 1) separator(sep);
		}
		newline();
		return v;
	}

	template <typename Tag>
	std::vector<std::string> gen_strings(const std::string& name, int count, int min, int max,
	                                     const std::string_view chars, Tag /*unused*/,
	                                     Separator sep) {
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

			assert(false && "Generating increasing/decreasing lists of strings is not "
			                "supported!");
		}

		newline();

		return v;
	}

	// Check the next character.
	bool peek(char c, const std::string& name = "") {
		if(gen) {
			// TODO
			// if(not name.empty() and params.contains(name)) {
			// return c == params.at(name).operator()<char>(0, 0, rng);
			//}
			return Random::bit(rng);
		}
		if(!ws) in >> std::ws;
		if(case_sensitive) return in.peek() == std::char_traits<char>::to_int_type(c);
		return tolower(in.peek()) == tolower(std::char_traits<char>::to_int_type(c));
	}

	// Read a string and make sure it equals `expected`.
	// Takes by value because it needs to lowercase its arguments.
	std::string test_strings(std::vector<std::string> expected, const std::string& name = "") {
		if(gen) {
			int index = 0;
			// TODO
			// if(not name.empty() and params.contains(name)) {
			// auto s = params.at(name).operator()<std::string>(0, 0, rng);
			// index  = std::find(expected.begin(), expected.end(), s) - expected.begin();
			// assert(0 <= index and index < expected.size());
			//} else {
			index = expected.size() == 1 ? 0 : uniform_number<int>(0, expected.size() - 1);
			//}
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
	std::string test_string(std::string expected, const std::string& name = "") {
		return test_strings({std::move(expected)}, name);
	}

	// Read an arbitrary string of a given length.
	template <typename Tag = ArbitraryTag>
	std::string read_string(const std::string& name, long long min, long long max,
	                        const std::string_view chars = "", Tag tag = Tag()) {
		if(gen) {
			return gen_string(name, min, max, chars);
		}
		std::string s = get_string();
		std::array<bool, 256> ok_char{};
		if(!chars.empty()) {
			for(auto c : chars) ok_char[c] = true;
			for(auto c : s)
				check(ok_char[c], name, ": expected characters in ", chars, " but found character ",
				      c, " in ", s);
		}
		check_string(name, min, max, s, tag);
		return s;
	}

	// Read an arbitrary line of a given length.
	std::string read_line(const std::string& name, long long min, long long max,
	                      const std::string_view chars = "") {
		if(gen) {
			// TODO: Params for lines.
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
		log_constraint("|" + name + "|", min, max, size);
		return s;
	}

	// Return ACCEPTED verdict.
	void eof_and_AC() {
		eof();
		AC();
	}

  private:
	std::function<void()> WA_handler = [] {};

  public:
	void set_WA_handler(std::function<void()> f) { WA_handler = std::move(f); }

	// Return WA with the given reason.
	template <typename... Ts>
	[[noreturn]] void WA(const Ts&... ts) {
		static_assert(sizeof...(Ts) > 0);

		WA_handler();

		auto pos = get_file_pos();
		std::cerr << pos.first << ":" << pos.second << ": ";

		WA_impl(ts...);
	}

	// Check that the condition is true.
	template <typename... Ts>
	void check(bool b, const Ts&... ts) {
		static_assert(sizeof...(Ts) > 0, "Provide a non-empty error message.");

		if(!b) WA(ts...);
	}

	// Log some value in a range.
	template <typename T>
	void log_constraint(const std::string& name, T low, T high, T v) {
		// All integer types get bounds as long long, all floating point types as long_double.
		using U = Bounds<std::conditional_t<std::is_integral_v<T>, long long, long double>>;

		auto [it, inserted] = bounds.emplace(name, U(name, v, v, low, high));
		assert(std::holds_alternative<U>(it->second));
		auto& done = std::get<U>(it->second);
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
		assert(!gen);
		std::string s = get_string("integer");
		if(s.empty()) {
			WA(name, ": Want integer, found nothing");
		}
		long long v;
		try {
			auto begin = s.c_str(), end = begin + s.size();
			auto [ptr, ec] = std::from_chars(begin, end, v);
			if(ptr != end or ec != std::errc{})
				WA(name, ": Parsing " + s + " as long long failed! Did not process all characters");
		} catch(const std::out_of_range& e) {
			WA(name, ": Number " + s + " does not fit in a long long!");
		} catch(const std::invalid_argument& e) {
			WA("Parsing " + s + " as long long failed!");
		}
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
		assert(!gen);
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
		} catch(const std::invalid_argument& e) {
			WA("Parsing " + s + " as long double failed!");
		}
		return v;
	}

	[[noreturn]] void expected(const std::string& exp = "", const std::string& s = "") {
		assert(!gen && "Expected is not supported for generators.");
		WA("Expected ", exp, ", found ", s.empty() ? "empty string" : s);
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
		if(in >> s) {
			return s;
		}
		expected(wanted, "nothing");
	}

	// Return ACCEPTED verdict.
	void AC() const {
		if(gen) {
			// nothing
			return;
		}

		exit(ret_AC);
	}

	void eof() {
		if(gen) {
			out.flush();
			fclose(stdout);
			return;
		}
		if(in.eof()) return;
		// Sometimes EOF hasn't been triggered yet.
		if(!ws) in >> std::ws;
		int c = in.get();
		if(c == std::char_traits<char>::eof()) return;
		std::string got = std::string("\"") + char(c) + '"';
		if(c == '\n') got = "newline";
		expected("EOF", got);
	}

  public:
	// Convert a string to lowercase is matching is not case sensitive.
	std::string& lowercase(std::string& s) const {
		if(case_sensitive) return s;
		transform(s.begin(), s.end(), s.begin(), [](unsigned char c) { return std::tolower(c); });
		return s;
	}

  private:
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

	std::unordered_map<std::string, std::variant<Bounds<long long>, Bounds<long double>>> bounds;

	void write_constraints() {
		if(constraints_file_path.empty()) return;

		std::ofstream os(constraints_file_path);

		for(const auto& [name, bound] : bounds) {
			std::visit(
			    [&](const auto& b) {
				    os << "LocationNotSupported:" << b.name << " " << b.name << " " << b.has_min
				       << " " << b.has_max << " " << b.min << " " << b.max << " " << b.low << " "
				       << b.high << std::endl;
			    },
			    bound);
		}
	}

	static const int ret_AC = 42, ret_WA = 43;
	std::istream& in  = std::cin;
	std::ostream& out = std::cout;

  public:
	const bool ws             = true;
	const bool case_sensitive = true;
	const std::string constraints_file_path;
	const bool gen = false;

	std::mt19937_64 rng;

  private:
	std::unordered_map<std::string, ParamGenerator> params;

  public:
	std::string_view get_param(std::string_view name, std::string_view default_) {
		auto it = params.find(std::string(name));
		if(it == params.end()) return default_;
		return std::get<std::string_view>(it->second.generator);
	}

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

class Generator : public Validator {
  public:
	explicit Generator(unsigned int seed)
	    : Validator(true, true, std::cin, /*constraints_file_path_=*/"", seed) {}
};

class InputValidator : public Validator {
  public:
	// An InputValidator is always both whitespace and case sensitive.
	explicit InputValidator(int argc = 0, char** argv = nullptr)
	    : Validator(true, true, std::cin, get_constraints_file(argc, argv), get_seed(argc, argv),
	                get_params(argc, argv)) {}

  private:
	static std::optional<unsigned int> get_seed(int argc, char** argv) {
		for(int i = 1; i < argc - 1; ++i) {
			if(argv[i] == generate_flag) {
				return std::stol(argv[i + 1]);
			}
		}
		// If no --generate is given, but `generat` is a substring of the binary path,
		// use the first argument as seed.
		if(std::string(argv[0]).find(generate_binary_substring) != std::string::npos) {
			return std::stol(argv[1]);
		}
		return std::nullopt;
	}

	static std::unordered_map<std::string, ParamGenerator> get_params(int argc, char** argv) {
		std::unordered_map<std::string, ParamGenerator> params;
		for(int i = 1; i < argc - 1; ++i) {
			if(std::strlen(argv[i]) == 0 or argv[i][0] != '-') continue;
			if(argv[i] == generate_flag) {
				continue;
			}
			std::string_view name(argv[i] + 1);
			std::string_view value(argv[i + 1]);
			params.insert({std::string(name), ParamGenerator(value)});
		}
		return params;
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

class AnswerValidator : public Validator {
  public:
	// An OutputValidator can be run in different modes.
	explicit AnswerValidator(int argc, char** argv, std::istream& in_ = std::cin)
	    : Validator(/*ws_sensitive=*/true, /*space sensitive*/ true, in_,
	                get_constraints_file(argc, argv)) {}
};
