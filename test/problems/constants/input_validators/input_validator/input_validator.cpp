#include "validation.h"

int main(int argc, char** argv) {
	InputValidator v(argc, argv);
	int n = v.read_integer("n", {{FIVE.INT}}, {{FIVE.STRING}});
	v.newline();
}
