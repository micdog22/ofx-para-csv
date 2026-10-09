"""Permite rodar com `python -m ofx_para_csv`."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
