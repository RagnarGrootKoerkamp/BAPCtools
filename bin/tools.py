#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK

import os
import sys
from pathlib import Path

import colorama
from colorama import Fore, Style

if not os.getenv("GITLAB_CI", False) and not os.getenv("CI", False):
    colorama.init()

if __name__ == "__main__":
    print(
        f"{Fore.YELLOW}"
        "%%%%%%%%%%%%%%%%%%%%%%%%%%%%\n"
        "%%  DEPRECATION WARNING!  %%\n"
        "%%%%%%%%%%%%%%%%%%%%%%%%%%%%\n"
        "Your BAPCtools installation uses the deprecated '/bin/tools.py' entry point, which will be removed in\n"
        "a future release.  Please update your BAPCtools installation to use '/bapctools/__main__.py' instead.\n"
        "It is recommended to install BAPCtools via pip(x).\n"
        f"{Style.RESET_ALL}"
    )

    # Add repository root to python path so that bapctools is importable. Notably, we need to
    # resolve __file__ as it would otherwise refer to the location of the symlink used to invoke
    # this script.
    sys.path.append(str(Path(__file__).resolve().parents[1]))

    from bapctools.cli import main

    main()
