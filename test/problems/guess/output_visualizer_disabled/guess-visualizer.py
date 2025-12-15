import sys
from pathlib import Path

with open(sys.argv[1]) as in_file, open(sys.argv[3] / Path("judgemessage.txt"), "r") as msg_file:
    mode = in_file.read().split()[0]
    assert mode in ("random", "fixed", "adaptive"), mode
    judgemessages = iter(msg_file)

    print(r"""\documentclass[varwidth]{standalone}
\usepackage{tikz}
\usetikzlibrary{patterns}
\tikzset{every node/.style={font=\sffamily}}
\begin{document}
\begin{tikzpicture}
    """)
    if not mode == "adaptive":
        secret = int(next(judgemessages).split()[-1])
        print(rf"\node at ({secret / 100},-1.5) {{ {secret} ({mode}) }};")
    else:
        next(judgemessages)
        print(r"\node at (5,-.5) { adaptive };")
    for line in judgemessages:
        rnd, guess = int(line.split()[1]), int(line.split()[3])
        y = -1 - rnd
        print(rf"\draw [very thick, blue!20] (0, {y}) -- (10, {y});")
        print(rf"\node at ({guess / 100}, {y})[anchor=north]", r"{$\uparrow$};")
        print(rf"\node at ({guess / 100}, {y - 0.5})[anchor=north] {{ {guess} }};")
    if not mode == "adaptive":
        print(rf"\draw [red] ({secret / 100}, {-rnd - 1}) -- ({secret / 100}, 0);")

    print(r"\end{tikzpicture}\end{document}")
