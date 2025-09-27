/*
 * This should give CORRECT on the default problem 'hello',
 * since the random extra file will not be passed to gcc.
 */

#include <stdio.h>

int main()
{
	char hello[20] = "Hello world!";
	printf("%s\n",hello);
	return 0;
}
