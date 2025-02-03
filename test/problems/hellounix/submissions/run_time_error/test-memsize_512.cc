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

int main() {
	std::cerr << "Trying to allocate at least: " << 513 << " MB" << std::endl;
	vector<char> v(513 * 1024 * 1024);
	std::cerr << "Allocated: " << v.size() << " MB" << std::endl;
	return 0;
}
