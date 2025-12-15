#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK

import sys
from pathlib import Path

if __name__ == "__main__":
    # Add repository root to python path so that bapctools is importable. Notably, we need to
    # resolve __file__ as it would otherwise refer to the location of the symlink used to invoke
    # this script.
    sys.path.append(str(Path(__file__).resolve().parents[1]))

    from bapctools.cli import main

    main()
