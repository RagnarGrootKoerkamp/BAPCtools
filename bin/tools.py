#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK

import sys
from pathlib import Path

if __name__ == "__main__":
    sys.path.append(str(Path(__file__).parent.parent.resolve()))

    from bapctools.cli import main

    main()
