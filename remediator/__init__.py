"""
ADA PDF Remediator Package.
Provides automated PDF accessibility remediation and WCAG / PDF/UA-1 compliance auditing.
"""

from .pipeline import remediate_single_pdf
from .compliance import run_compliance_check

__all__ = [
    "remediate_single_pdf",
    "run_compliance_check"
]
