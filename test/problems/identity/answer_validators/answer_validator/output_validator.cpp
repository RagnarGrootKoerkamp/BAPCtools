#include "validation.h"

int main(int argc, char** argv) {
	AnswerValidator v(argc, argv);
	int answer = v.read_integer("answer", 0, 1000);
	v.newline();
}
