"""Allow `python -m codereview` to invoke the CLI."""
import sys

from codereview.cli import main

if __name__ == "__main__":
    sys.exit(main())