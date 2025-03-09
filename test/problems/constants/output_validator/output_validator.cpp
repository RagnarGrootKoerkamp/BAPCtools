#include "validation.h"

int main(int argc, char *argv[]) {
    // Set up the input and answer streams.
    std::ifstream in(argv[1]);
    OutputValidator v(argc, argv);

    int input;
    in >> input;
    int answer = v.read_integer("answer", {{INT_FIVE}}, {{STRING_FIVE}});
    v.newline();
}
