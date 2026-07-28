#!/usr/bin/env python3
"""WSGI entry point.

The implementation lives in :mod:`remediator.service`, which exposes an
application factory so tests can build an isolated instance. This module exists
so ``gunicorn app:app`` and ``python app.py`` keep working.
"""

from __future__ import annotations

import os

from remediator.service import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=False)
