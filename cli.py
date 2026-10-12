"""Compatibility wrapper for the autopath CLI.

The canonical CLI lives in src/autopath/cli.py.
"""

from autopath.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
