#include <iostream>
int main(int argc, char** argv){
	for(int i = 1; i < argc; ++i){
		if(i > 1)
			std::cout << ' ';
		std::cout << argv[i];
	}
	std::cout << std::endl;
}
