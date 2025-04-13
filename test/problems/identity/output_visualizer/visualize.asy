defaultpen(1);

string outvalue = stdin;

string infilename;
string ansfilename;
usersetting();
file fin=input(infilename);
file fans=input(infilename);
string invalue = fin;
string ansvalue = fans;

string label = "\texttt{in}: " + invalue ;
label(scale(5)*label, (0,200));
string label = "\texttt{ans}: " + ansvalue ;
label(scale(5)*label, (0,100));
pen labelPen = (invalue == outvalue) ? green : red;
string label = "\texttt{out}: " + outvalue ;
label(scale(5)*label, (0,0), p=labelPen);
shipout(bbox(xmargin=5, white, Fill));
