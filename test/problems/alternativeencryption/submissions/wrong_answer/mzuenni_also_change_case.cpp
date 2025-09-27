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
		for (char& c : a) c = (((c + 1) ^ 1) - 1) ^ 0x20;
		cout << a << endl;
	}
}
