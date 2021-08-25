# BAPC/NWERC Problem Statement Styleguide

## Input Sections

Input Sections are in "Dutch style". Most items exactly follow one of the
forms in this sample:

### Input

The input consists of:

- One line with an integer $n$ ($1 \le n \le 10$), the number of Blah.
- One line with two integers $n$ and $m$ ($1 \le n \le 10$, $1\le m \le 100$),
  the number of Foo and the number of Bar.
- One line with $n$ integers $a_1, \ldots, a_n$ ($0\le a_i\le 10^9$ for each $i$),
  where $a_i$ is the value of Foo.
- $n$ lines, each with an integer $k$ ($0\leq k \leq 100$), ...
- $n$ lines, the $i$th of which contains two integers ...
- $n$ lines, each containing two numbers describing an event:
  - An integer $e$ ($1\leq e\leq 5$) the type of the event, and
  - a real number $p$ ($0 < p < 1$ with at most $6$ digits after the decimal point),
    the probability of succes.

An optional remark regarding additional guarantees goes here, i.e. that a graph
is connected or all input strings have length between $1$ and $20$ characters
and only consist of lowercase letters.

<details><summary>LaTeX source</summary>

```latex
\begin{Input}
    The input consists of:
    \begin{itemize}
        \item One line with an integer $n$ ($1 \le n \le 10$), the number of Blah.
        \item One line with two integers $n$ and $m$ ($1 \le n \le 10$, $1\le m \le 100$),
            the number of Foo and the number of Bar.
        \item One line with $n$ integers $a_1, \ldots, a_n$ ($0\le a_i\le 10^9$ for each $i$),
            where $a_i$ is the value of Foo.
        \item $n$ lines, each with an integer $k$ ($0\leq k \leq 100$), ...
        \item $n$ lines, the $i$th of which contains two integers ...
        \item $n$ lines, each containing two numbers describing an event:
        \begin{itemize}
            \item An integer $e$ ($1\leq e\leq 5$) the type of the event, and
            \item a real number $p$ ($0 < p < 1$ with at most $6$ digits after the decimal point),
                the probability of succes.
        \end{itemize}
        \end{itemize}
    \end{itemize}
    An optional remark regarding additional guarantees goes here, i.e. that a graph
    is connected or all input strings have length between $1$ and $20$ characters
    and only consist of lowercase letters.
\end{Input}
```

</details>

### Remarks

- Items end with a full stop.
- Use wording `One line with ...`.
- Use a comma between the description of what appears in input and the description of what it means.
- Do not write `single`. Just say `One line with an integer $n$`.
- When possible, mention all variables at the start of the sentence: `One line with two integers $n$ and $m$ (..), ...`.
- When using indices, always quantify over them properly.
- Don't introduce indices unless you need them.
- Do not write "separated by single spaces" and similar general
  formatting rules that always apply (but if for some reason amount of
  spaces may vary, do write this).

| Don't                                                                                                          | Do                                                                                  |
| -------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| `One line without a period`                                                                                    | `One line ending in a period.`                                                      |
| `A line with ...`, `One line containing ...`                                                                   | `One line with ... `                                                                |
| `One line with an integer $n$ not separated by a comma.`                                                       | `One line with an integer $n$, separated by a comma.`                               |
| `One line with a single integer $n$.`                                                                          | `One line with an integer $n$.`                                                     |
| `One line with $n$ (..), the number of X, and $m$ (..), the number of Y.`                                      | `One line with two integers $n$ and $m$ (..), the number of X and the number of Y.` |
| `$n$ lines each containing an integer $x_i$`                                                                   | `$n$ lines, the $i$th of which contains an integer $x_i$`                           |
| `One line with $n$ integers $x_i$ ($1 \le x_i \le 100$)`                                                       | `One line with $n$ integers $x_1, \ldots, x_n$ ($1 \le x_i \le 100$ for all $i$)`   |
| `$n$ lines, the $i$th of which contains an integer $x_i$ ($0 \le x_i \le 10$)` without refering to the $x_i$'s | `$n$ lines, each containing an integer $x$ ($0 \le x \le 10$)`                      |

## Output Sections

- Write `Output an integer`: `Output the number of {ABC} such that {XYZ}.`
- Don't use funny output phrases, just plain
  `yes`/`no`/`possible`/`impossible` (and all lower case), whichever is
  appropriate. The statement should both quote and texttt the text:
  ```
  ``\texttt{impossible}''
  ```
- Output is usually not space sensitive - don't write `Output one line ...`,
  just write `Output ...`
- Even when the output goes on multiple lines, just writing `Output the number of integers, followed by these integers.` is usually sufficient.
- If the problem is to find something or output impossible: ` If {ABC} then output {XYZ}. Otherwise, output ``\texttt{impossible}''. `
- Real-valued tolerance: `Your answer should have an absolute or relative error of at most 10−6.` (with $10^{-6}$ replaced by
  whatever tolerance the problem uses)
- Accepting any valid solution: `If there are multiple valid/optimal solutions, you may output any one of them.`
- Imposing technical restrictions on the output not part of the
  underlying problem, for the purposes of making judging feasible:
  describe these after the general description of the output format
  (c.f. NWERC 2018 Circuit Design and NWERC 2018 Game Design).

## General guidelines

Try to keep the Latex code as clean as possible, avoiding contorted
tweaks to get your problem to look like you want. It should be
possible to convert the problem statement to both pdf and html
reliably.

- We use British English for the statements.
- Variable names: use lower case `$n$`, `$m$`, etc for numeric variables.
  For other types of variables, e.g. set-valued variables, upper case may be better.
- The default is to use $1$-based indexing of e.g. nodes in graphs and
  other sets of items given serial IDs, but in cases where $0$-based
  indexing becomes cleaner this may be OK (e.g. if there are lists of
  $n+1$ things, naming them $x_0$ up to $x_n$ may be preferable).
- Don't use phrases along the lines of "Can you help protagonist do
  X?" (in particular in cases when the answer is always yes for a
  sufficiently competent value of "you"). Instead use imperative
  form: "Help X with Y."
- Avoid long lines in the Latex source. Shorter lines usually give better commit
  diffs where there are small changes. Either wrapping at 80/100 chars or at the
  end of sentences is fine.
- Use variables for the problem bounds, and name them specific to the problem:
  `\newcommand{\Amaxn}{10^9}`.

## Formatting/typesetting details

- Use exponents where reasonable, e.g. `$10^6$` rather than `$1\,000\,000$`.
- For large numbers, use `\,` (small space) to create groups of three
  digits, e.g. `$2\,500$`: $2\,500$ instead of $2500$.
- Always put numbers in math mode throughout the text, e.g. $42$
  rather than 42.
- $i$th (`$i$th`), not $i$:th, $i$-th, or $i$'th.
- Do not use contractions (i.e., write "do not" instead of "don't", etc)
- Formatting units: $1\text{ cm}$ (`$1\text{ cm}$`) etc.
- String literals are both ` ``quoted'' ` and `\texttt`:
  $``\texttt{impossible}''$.
  ```
  ``\texttt{impossible}''
  ```
  Quotes start with
  two backticks, and end with two single quotes.
  Single characters can be quoted by a single backtick/quote: $`\texttt{a}'$:
  ```
  `\texttt{a}'
  ```

## Images

We distinguish between two types of pictures used in problem
statements: illustrations and figures.

An **illustration** is a non-essential eye candy picture whose only
purpose is to make the problem statement look prettier. The template
provides a command `\illustration{width%}{image}{attribution}` to
typeset illustrations. Its arguments are:

- `width%`: a number between 0 and 1, the desired width of the illustration, as fraction of the total page width.
- `image`: the image file to be included.
- `attribution`: attribution for the image

```
\illustration{0.3}{image.jpg}{\href{https://www.some.url}{Figure} by Person, Pixabay} % CC-BY-SA
```

A **figure** is an essential picture explaining or clarifying some
part of the problem statement. Figures should be typeset using the
standard Latex figure environment and `\includegraphics`. A typical use
would be:

```
\begin{figure}[!h]
\centering
\includegraphics[width=0.5\textwidth]{snarks}
\caption{The seven different snarks}
\label{fig:snarks}
\end{figure}
```

The figure can (and should!) then be referenced by writing `Figure~\ref{fig:snarks}` in the text.
