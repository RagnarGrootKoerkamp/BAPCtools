# Multiple Language Support

The 
[Problem Package Format Specification](https://www.kattis.com/problem-package-format/)
supports multiple (natural) languages for statements in the form of `prolem_statement/problem.LANG.tex`  and problem names in the `problem.yaml` metadata of the form

```yaml
name:
  en: Hello World
  fr: Bonjour le monde
```

Here, `LANG` is a two-letter language code, see 
[List of ISO 639-1 codes](https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes).

It is expected that the languages keys in the metadata and statement files agree. 

The default language for BAPCtools is English, but multiple languages can be specified at various points of the tool, typically using the `--language` flag or configuration files.

## Creating a contest

In short,

1. configure `languages` in `.bapctools.yaml`.
2. add a skeleton for `problem.LANG.tex` in `skel/problem/problem_statement`.

### Configure `language`

To create a contest supporting French, Dutch, and Luxembourgish, set the configurartion key `languages` to the list `['nl', 'fr', 'lt']`.
Configuration keys can be set in many ways, see **Personal configuration file** in the BAPCtools documentation, but an easy way is to create a new contest:

```sh
bt new_contest
```

and then create or extend the file `<contestdirectory>/.bapctools.yaml` with
```yaml
languages:
- nl
- fr
- lt
```

### Add skeleton statements

The skeleton directory for a new problem statement (see `bt skel` and `bt new_problem`) by default only supports English and will populate `<problem_name>/problem_statement/problem.en.tex` with a default statement.
To support, *e.g.*, German, you need to add `problem.de.tex`.
To do this automatically for each `bt new_problem`, create a problem skeleton in `<contestdirectory>/skel/problem`, and add `problem_statement/problem.de.tex`, for instance like this: 
```tex
\problemname{\problemyamlname} % replaced by name['de'] from problem.yaml

Lorem ipsum…

\section*{Eingabe}

Lorem ipsum…

\section*{Ausgabe}

Lorem ipsum…
```

Note that the environment `\begin{Input}…\end{Input}` used by `problem.en.tex` will produce English section headings, which is probably not what you want.


## Creating a problem

To create a problem,

```sh
bt new_problem
```

will look for the `languages` configuration (for intance, at constest level) and use that by default.
Thus, if the contest is set up as above, you need to do nothing extra.

With arguments, or outside of a contest directory,
```sh
bt new_problem --language en --language fr
```
creates a problem with two languages, English and French.
If no languages are configured, it creates `en`.

# Problem PDFs

At problem level, without arguments,

```sh
bt pdf
```
creates PDFs for every problem language statement `problem.xy.tex`.
With arguments,
```sh
bt pdf --language en --language fr
```
produces PDFs for English and French.

The resulting PDFs are named  `<problemdirectory>/problem.xy.pdf`.
The exception is if only a single statement is produced, in which case it it moved to `problem.pdf`.
(This ensures consistency with monolingual use and with the expectations of various judging platforms.)

# Contest and solution PDFs, Export

Multiple-language support of `bt pdf` at contest level, `bt solutions`, and `bt export` is incomplete and inconsistent.
