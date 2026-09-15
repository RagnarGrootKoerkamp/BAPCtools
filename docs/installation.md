# Installation

!!! info
    The latest version of BAPCtools is designed for the lasted version of the problem format: [`2025-09`](https://icpc.io/problem-package-format/spec/2025-09.html).
    The [`bt upgrade` command](https://github.com/RagnarGrootKoerkamp/BAPCtools/blob/HEAD/doc/commands.md#upgrade) is a best-effort automated way to upgrade older packages to `2025-09`.
    If you are working on older packages, we recommend to upgrade them.
    If you do not want this, you can also switch to the [`legacy` branch](https://github.com/RagnarGrootKoerkamp/BAPCtools/tree/legacy).
    However, keep in mind that this version is no longer actively maintained.

There are multiple ways to install BAPCtools:

- From [PyPI](https://pypi.org/p/bapctools/): `pip(x) install bapctools`.
  This should be a complete installation (including all dependencies and a `bt` executable) and should work on any Linux-ish system.
- The [bapctools-git AUR package](https://aur.archlinux.org/packages/bapctools-git/),
  mirrored [here](https://github.com/RagnarGrootKoerkamp/bapctools-git).
- Run from a [Docker image](#docker).
- The current version from git via `pip install .`.
  For more information regarding the development version see the installation instructions [here](contribute.md).

(If you know how to make a Debian package, feel free to help out.)

## Windows
!!! tip
    For Windows, the preferred way to use BAPCtools is inside the Windows Subsystem for Linux (WSL).

Note that BAPCtools makes use of symlinks for building programs.
By default, users are not allowed to create symlinks on Windows.
This can be fixed by enabling Developer Mode on Windows (only since Windows 10 version 1703, or newer).<br>
In case you're still having problems with symlinks in combination with Git after enabling this setting, please try the suggestions at https://stackoverflow.com/a/59761201.
Specifically, `git config -g core.symlinks true` should do the trick, after which you can restore broken symlinks using `git checkout -- path/to/symlink`.

## Native Windows
If you cannot or do not want to use WSL, you'll need the following in your `%PATH%`:

- `python` for Python 3
- `g++` to compile C++
- `javac` and `java` to compile and run Java.
- `pyctd` for checktestdata, see [PyCTD](https://github.com/mzuenni/pyctd)

!!! note
    Some features do not work on native windows:

    - Resource limits like memory limit/hard cpu time limit...
    - Core pinning
    - argparse auto completion
    - Logging interactions for interactive problems
    - maybe more

## Docker

A docker image containing this git repo and dependencies, together with commonly used languages, is provided at [ragnargrootkoerkamp/bapctools](https://hub.docker.com/r/ragnargrootkoerkamp/bapctools).
This version may be somewhat outdated, but we intend to update it whenever dependencies change.
Ping us if you'd like it to be updated.
Alternatively, inside the Docker container, you can run `git -C /opt/BAPCtools pull` to update to the latest version of BAPCtools, and use `pacman -Sy <package>` to install potential missing dependencies.
<!-- TODO: update the Docker image to use installation via Pip. -->

This image can be used for e.g.:

- running CI on your repo.
  Also see `bt gitlabci` which generates a `.gitlab-ci.yaml` file.
  Make sure to clear the entrypoint, e.g. `entrypoint: [""]`.
- running `bt` on your local problems.
  Use this command to mount your local directory into the docker image and run a command on it:
  ```sh
  docker run -v $PWD:/data --rm -it ragnargrootkoerkamp/bapctools <bt subcommands>
  ```
