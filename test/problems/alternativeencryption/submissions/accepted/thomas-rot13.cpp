/**
 * Author: Thomas Beuman
 *
 * Rot-13: A <-> N, B <-> O, C <-> P, ..., M <-> Z
 * Is symmetric, so encryption and decryption are the same
 *
 * This solution contains some preset encryptions (the ones present in the sample)
 */

#include <cstdio>
#include <map>
#include <string>
using namespace std;

const int M = 100;

string FixedAnswers[3][2] = {
	{"plaintext", "encrypted"},
	{"nwerc", "delft"},
	{"correct", "balloon"}
};

string rot13 (string s)
{
	int n = s.size();
	string res(n, ' ');
	for (int i = 0; i < n; i++) {
		int c = s[i]-'a';
		c = (c + 13) % 26;
		res[i] = 'a'+c;
	}
	return res;
}

int main()
{
	// Set some fixed answers to generate the samples
	map<string,string> Fixed;
	for (int i = 0; i < 3; i++) {
		string dec = FixedAnswers[i][0];
		string enc = FixedAnswers[i][1];
		Fixed[dec] = enc;
		Fixed[enc] = dec;
		// Pair up their old partners
		enc = rot13(FixedAnswers[i][0]);
		dec = rot13(FixedAnswers[i][1]);
		Fixed[dec] = enc;
		Fixed[enc] = dec;
	}

	int n;
	scanf("%*s"); // Do not care about e
	scanf("%d", &n);
	for (int i = 0; i < n; i++) {
		char buf[M+1];
		scanf("%s", buf);
		string s = buf;
		string res;
		if (Fixed.count(s))
			res = Fixed[s];
		else
			res = rot13(s);
		printf("%s\n", res.c_str());
	}
	return 0;
}
