"""Geometric primitives shared across the pipeline.

Figure detection, contrast analysis and reading order all need the same view of
where things sit on the page, so the primitives live in one place rather than
being reimplemented per feature.
"""

from __future__ import annotations

from .boxes import Box, cluster_boxes, significant_regions

__all__ = ["Box", "cluster_boxes", "significant_regions"]
