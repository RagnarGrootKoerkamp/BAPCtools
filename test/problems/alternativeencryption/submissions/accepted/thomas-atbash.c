/**
 * Author: Thomas Beuman
 *
 * Atbash: A <-> Z, B <-> Y, C <-> X, ...
 * Is symmetric, so encryption and decryption are the same
 */

#include <stdio.h>
#include <string.h>

const int M = 100;

int main()
{
	int n;
	scanf("%*s"); // Do not care about e
	scanf("%d", &n);
	for (int i = 0; i < n; i++) {
		char s[M+1];
		scanf("%s", s);
		int m = strlen(s);
		for (int j = 0; j < m; j++)
			printf("%c", 'a'+'z'-s[j]);
		printf("\n");
	}
	return 0;
}
