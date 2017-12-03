#include <iostream>

// If your problem needs more validation than just the grammar,
// for example, to check that a graph is connected, you can do so here.
// Your program must return 42 when the input is correct.
// When there is something wrong with the input, return 43.
// In this case, it is also a good idea to print some useful debug information to stdout.

// When your program crashes unexpectedly, or something weird is going on,
// please write some info to stderr and return anything different from 42 and 43.

const int AC = 42, WA = 43;

int main() {
	int n;
	std::cin >> n;
	if(0 <= n && n <= 100000)
		return AC;
	else {
		std::cout << "The input (n) is not between 0 and 100000!" << std::endl;
		return WA;
	}
}
