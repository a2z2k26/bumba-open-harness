"""Memory dual-write pipeline — write-fanout primitive for primary + optional secondary stores.

Preserved for future RAG/memory-tiers sprint per operator decision 2026-05-12 (#1719).
"""
from __future__ import annotations

from .dual_write import DualWriteResult, DualWritePipeline

__all__ = [
    "DualWriteResult",
    "DualWritePipeline",
]
