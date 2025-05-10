#include <iostream>
using namespace std;

#define all(x) begin(x), end(x)
#define sz(x) (ll)(x).size()

using ll = long long;
using ld = long double;

int main() {
	ios_base::sync_with_stdio(false);
	cin.tie(nullptr);
	string a;
	ll n;
	cin >> a >> n;
	for (ll i = 0; i < n; i++) {
		cin >> a;
		if (a == "plaintext") a = "encrypted";
		else if (a == "encrypted") a = "plaintext";
		else if (a == "nwerc") a = "delft";
		else if (a == "delft") a = "nwerc";
		else if (a == "correct") a = "balloon";
		else if (a == "balloon") a = "correct";
		else for (char& c : a) c = ((c + 1) ^ 1) - 1;
		cout << a << endl;
	}
}
