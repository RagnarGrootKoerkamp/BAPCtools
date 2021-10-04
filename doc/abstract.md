# BAPCtools - software for streamlining problem development

Over the years, [BAPCtools](https://github.com/RagnarGrootKoerkamp/BAPCtools)
has grown from a collection of scripts used in the BAPC (Benelux Algorithm
Programming Contest) jury to a full blown command line application for problem
development. It targets the CLICS problem package format as used by DOMjudge and Kattis,
and is now also used by the NWERC jury. Good user experience and convenience of
use, including an intuitive command line interface and clear output, are
explicit goals.

In this talk, I will develop a new problem from scratch and show some of
BAPCtools' features, like:

- automatically judging submissions to a problem,
- a C++ library for input/output validation,
- a new specification for generating test cases reproducibly,
- fuzz testing submissions.
