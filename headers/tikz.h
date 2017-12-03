#include <array>
#include <iostream>
#include <map>
#include <vector>
using namespace std;

struct tikzpicture {
	const string header = R"(
\documentclass[convert={outext=.png},border=5pt]{standalone}
\usepackage{tikz}
\usetikzlibrary{backgrounds}
\begin{document}
\begin{tikzpicture}[show background rectangle,background rectangle/.style={fill=white}]
)";
	const string footer = R"(
\end{tikzpicture}
\end{document}
)";

	struct arguments : map<string, string> {
		arguments() {}
		arguments(const map<string, string> &m) : map<string, string>{m} {}
		// arguments(const map<char *, char *> &m) {
		// for(auto kv : m) emplace(kv.first, kv.second);
		//}
		arguments(const arguments &a) : map<string, string>(a) {}
		friend ostream &operator<<(ostream &o, const arguments &args) {
			if(args.size() == 0) return o;
			bool first = true;
			for(auto arg : args) {
				if(first)
					first = false;
				else
					o << ',';
				if(arg.second.empty())
					o << arg.first;
				else
					o << arg.first << "=" << arg.second;
			}
			return o;
		}
	};

	struct object {
		tikzpicture &tp;
		arguments args = {};
	};

	struct point {
		double x, y;
		friend ostream &operator<<(ostream &o, const point &p) {
			return o << "(" << p.x << "," << p.y << ")";
		}
		friend point max(point l, point r) { return {max(l.x, r.x), max(l.y, r.y)}; }
		friend point min(point l, point r) { return {min(l.x, r.x), min(l.y, r.y)}; }
	};

	struct tikzpoint : object, point {
		friend ostream &operator<<(ostream &o, const tikzpoint &p) {
			return o << "\\node[draw," << p.args << "]"
			         << " at " << p.tp.scale(p) << " {} ;";
		}
	};

	using segment = array<point, 2>;

	struct tikzsegment : object, segment {
		friend ostream &operator<<(ostream &o, const tikzsegment &l) {
			return o << "\\draw[" << l.args << "] " << l.tp.scale(l[0]) << " -- "
			         << l.tp.scale(l[1]) << " ;";
		}
	};

	struct circle {
		point c;
		double r;
	};

	struct tikzcircle : object, circle {
		friend ostream &operator<<(ostream &o, const tikzcircle &c) {
			return o << "\\draw[" << c.args << "] " << c.tp.scale(c.c) << " circle ("
			         << c.tp.scale(c.r) << ") ;";
		}
	};

	vector<tikzpoint> points;
	vector<tikzsegment> segments;
	vector<tikzcircle> circles;

	mutable double s;
	mutable point low, high;

	void get_scale() const {
		low                       = {1e9, 1e9};
		high                      = {-1e9, -1e9};
		for(auto &p : points) low = min(low, p), high = max(high, p);
		for(auto &s : segments)
			for(int i : {0, 1}) low = min(low, s[i]), high = max(high, s[i]);
		for(auto &c : circles)
			low  = min(low, {c.c.x - c.r, c.c.y - c.r}),
			high = min(high, {c.c.x + c.r, c.c.y + c.r});
		s        = 10.L / max(high.x - low.x, high.y - low.y);
	}
	point scale(const point &p) { return {(p.x - low.x) * s, (p.y - low.y) * s}; }
	double scale(double d) { return s * d; }
	friend ostream &operator<<(ostream &o, const tikzpicture &tp) {
		tp.get_scale();
		o << tp.header;
		for(const auto &x : tp.segments) o << x << '\n';
		for(const auto &x : tp.circles) o << x << '\n';
		for(const auto &x : tp.points) o << x << '\n';
		o << tp.footer;
		return o;
	}

	void add_point(point p, arguments args = {}) { points.push_back({{*this, args}, p}); }
	void add_point(double x, double y, arguments args = {}) {
		points.push_back({{*this, args}, {x, y}});
	}
	void add_segment(segment s, arguments args = {}) { segments.push_back({{*this, args}, s}); }
	void add_segment(double px, double py, double qx, double qy, arguments args = {}) {
		segments.push_back({{*this, args}, {{{px, py}, {qx, qy}}}});
	}
	void add_circle(circle c, arguments args = {}) { circles.push_back({{*this, args}, c}); }
	void add_circle(double x, double y, double r, arguments args = {}) {
		circles.push_back({{*this, args}, {{x, y}, r}});
	}
};
