# Commands

The commands here are roughly sorted per category.
If you search a specific command, just use the search.
The [implementation notes](../advanced/implementation_notes.md) contain more information about various topic not covered here.

Unless otherwise specified, commands work both on the problem and contest level.

!!! TIP
    Allowed subcommands and options are also available with `bt --help` and `bt <command> --help`.

## Global flags

The flags below work for any subcommand:

- `--verbose`/`-v`: Without this, only failing steps are printed to the terminal.
With `-v`, progress bars print one line for each processed item.
Pass `-v` twice to see all commands that are executed.
- `--contest <directory>`: The directory of the contest to use, if not the current directory.
At most one of `--contest` and `--problem` may be used.
Useful in CI jobs.
- `--problem <directory>`: The directory of the problem to use, if not the current directory.
At most one of `--contest` and `--problem` may be used.
Useful in CI jobs.
- `--memory <MB>`/`-m <MB>`: Override the maximum amount of memory in MB a program (submission/generator/etc.) may use.
- `--no-bar`: Disable showing progress bars.
This is useful when running in non-interactive contexts (such as CI jobs) or on platforms/terminals that don't handle the progress bars well.
- `--error`/`-e`: show full output of failing commands using `--error`.
The default is to show a short snippet only.
- `--force-build`: Force rebuilding binaries instead of reusing cached version.
- `--lang`: select languages to use for LaTeX commands.
The languages should be specified by language codes like `en` or `nl`.
