/*
 * This should give CORRECT on the default problem 'hello',
 * since the random extra file will not be passed to g++.
 */

#include <iostream>
#include <string>

using namespace std;

int main()
{
	string hello("Hello world!");
	cout << hello << endl;
	return 0;
}
