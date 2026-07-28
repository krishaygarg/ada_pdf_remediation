#!/usr/bin/env python3
"""Convenience wrapper so ``python check_compliance.py`` keeps working.

The implementation lives in :mod:`remediator.cli.compliance` so that the
installed ``check-compliance`` console script resolves without the repository
root on ``sys.path``.
"""

from __future__ import annotations

from remediator.cli.compliance import main

if __name__ == "__main__":
    raise SystemExit(main())
