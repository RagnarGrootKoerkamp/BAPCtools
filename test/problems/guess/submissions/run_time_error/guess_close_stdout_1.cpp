#include <cassert>
#include <chrono>
#include <cstdio>
#include <thread>
int main() {
	using namespace std::chrono_literals;
	std::fclose(stdout);
	std::this_thread::sleep_for(1s);
	assert(false);
}
