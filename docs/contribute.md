# Contributing

The recommended way to install all development dependencies is in a virtual environment,
created with `python3 -m venv venv` and activated with `. venv/bin/activate`.<br />
Install the development dependencies with `pip install --editable . --group dev`.

If you want to use your local development version of BAPCtools anywhere, you can create a symlink from any `bin` directory on your `$PATH` to the virtual environment, for example: `ln -s /path/to/BAPCtools/venv/bin/bt ~/bin/bt`.

The Python code in the repository is formatted using [Ruff](https://github.com/astral-sh/ruff) and type-checked using [mypy](https://mypy-lang.org/).
To enable the pre-commit hook, run `pre-commit install` from the repository root.
All Python code will now automatically be formatted and type-checked on each commit.
If you want to run the hooks before creating a commit, use `pre-commit run` (only staged files) or `pre-commit run -a` (all files).
