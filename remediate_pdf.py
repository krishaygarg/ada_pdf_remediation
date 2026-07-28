#!/usr/bin/env python3
"""Convenience wrapper so ``python remediate_pdf.py`` keeps working.

The implementation lives in :mod:`remediator.cli.remediate` so that the
installed ``remediate-pdf`` console script resolves without the repository
root on ``sys.path``.
"""

from __future__ import annotations

from remediator.cli.remediate import main

if __name__ == "__main__":
    raise SystemExit(main())
