/*
 * This should fail with RUN-ERROR due to a segmentation fault,
 * giving an exitcode 139.
 */

int main() {
	int a[10];
	int* b;

	b  = (int*)10;
	*b = a[-1000000];

	return 0;
}
