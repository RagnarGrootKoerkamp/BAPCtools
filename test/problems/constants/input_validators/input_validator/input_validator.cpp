#include "validation.h"

int main(int argc, char** argv) {
	InputValidator v(argc, argv);
	int n = v.read_integer("n", {{INT_FIVE}}, {{STRING_FIVE}});
	v.newline();
}
