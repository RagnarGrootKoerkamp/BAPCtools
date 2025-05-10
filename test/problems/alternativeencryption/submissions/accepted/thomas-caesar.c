/**
 * Author: Thomas Beuman
 *
 * Classic Caesar cipher (rot-23): A->X, B->Y, C->Z, D->A, ..., Z->W
 */

#include <stdio.h>
#include <string.h>

const int M = 100;

int main() {
	char mode[50];
	int n;
	scanf("%s", mode);
	scanf("%d", &n);
	int e = (strcmp(mode, "encrypt") == 0);
	for(int i = 0; i < n; i++) {
		char s[M + 1];
		scanf("%s", s);
		int m = strlen(s);
		for(int j = 0; j < m; j++) {
			int c = s[j] - 'a';
			c     = (c + (e ? 3 : 23)) % 26;
			printf("%c", 'a' + c);
		}
		printf("\n");
	}
	return 0;
}
