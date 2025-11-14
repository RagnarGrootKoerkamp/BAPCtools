#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK

from pathlib import Path
import sys

if __name__ == "__main__":
    sys.path.append(str(Path(__file__).parent.parent.resolve()))

    from bapctools.cli import main

    main()
