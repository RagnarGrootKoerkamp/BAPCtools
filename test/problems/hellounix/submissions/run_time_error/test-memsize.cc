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

const size_t inc_mb = 128;

template<typename T>
T use(std::vector<T>& todo) {
	if (todo.empty()) return {};
	volatile T* p = &todo[0];
	// reading a volatile pointer is a side effect and cannot be optimized
	return p[0];
}

int main() {
	vector<vector<char>> vs;
	while(true) {
		vs.emplace_back(inc_mb * 1024 * 1024);
		std::cerr << "Allocated: " << inc_mb * vs.size() << " MB (" << use(vs.back()) << ")" << std::endl;
	}
	return 0;
}
