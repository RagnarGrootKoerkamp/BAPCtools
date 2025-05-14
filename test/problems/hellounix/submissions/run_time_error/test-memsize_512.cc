/*
 * This should fail with RUN-ERROR due to running out of memory, which
 * is restricted.
 *
 * Note: This may try to create a coredump on exit and time out. This
 * can be prevented with `ulimit -c 0`.
 */

#include <iostream>
#include <vector>

using namespace std;

const size_t mb = 513;

template<typename T>
T use(std::vector<T>& todo) {
	// init with some data
	for (std::size_t i = 0; i < todo.size(); i++) todo[i] = T(i % 7);
	// do some computation that needs the memory
	for (int k = 0; k < 7; k++) {
		for (std::size_t i = 0; i < todo.size(); i++) {
			std::size_t j = (i + todo[i]) % todo.size();
			todo[j] = (todo[i] % 7) + (todo[j] % 7);
		}
	}
	// accumulate the result
	T res = 0;
	for (auto x : todo) res = (res >> 1) + (x >> 1);
	return res;
}

int main() {
	std::cerr << "Trying to allocate at least: " << mb << " MB" << std::endl;
	vector<char> v(mb * 1024 * 1024);
	std::cerr << "Allocated: " << mb << " MB (" << use(v) << ")" << std::endl;
	return 0;
}
