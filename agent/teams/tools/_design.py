"""Design department tool functions."""

from __future__ import annotations

import logging
from pydantic_ai import RunContext

from teams._types import BridgeDeps

log = logging.getLogger(__name__)


async def search_design_system(ctx: RunContext[BridgeDeps], query: str) -> str:
    """Search the shared design system knowledge store."""
    try:
        results = await ctx.deps.knowledge_search(f"design:{query}", limit=10)
        if not results:
            return f"No design system entries for: {query}"
        return "\n\n".join(str(r) for r in results)
    except Exception as e:  # noqa: BLE001
        log.exception("search_design_system failed")
        return f"ERROR: {e}"


async def lookup_component(ctx: RunContext[BridgeDeps], component_name: str) -> str:
    """Look up a specific design system component by name."""
    return await search_design_system(ctx, f"component:{component_name}")


async def recall_brand_guidelines(ctx: RunContext[BridgeDeps]) -> str:
    """Recall the current brand guidelines (colors, typography, voice)."""
    try:
        result = await ctx.deps.memory_store.get("brand:guidelines")
        return str(result) if result else "No brand guidelines stored"
    except Exception as e:  # noqa: BLE001
        log.exception("recall_brand_guidelines failed")
        return f"ERROR: {e}"


async def check_wcag_contrast(
    ctx: RunContext[BridgeDeps], foreground: str, background: str
) -> str:
    """Calculate WCAG contrast ratio between two hex colors."""
    def _hex_to_rgb(h: str) -> tuple[int, int, int]:
        h = h.lstrip("#")
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

    def _luminance(rgb: tuple[int, int, int]) -> float:
        def _ch(v: int) -> float:
            s = v / 255.0
            return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4
        r, g, b = rgb
        return 0.2126 * _ch(r) + 0.7152 * _ch(g) + 0.0722 * _ch(b)

    try:
        fg_lum = _luminance(_hex_to_rgb(foreground))
        bg_lum = _luminance(_hex_to_rgb(background))
        ratio = (max(fg_lum, bg_lum) + 0.05) / (min(fg_lum, bg_lum) + 0.05)
    except (ValueError, IndexError) as e:
        return f"ERROR: invalid hex color: {e}"

    aa_normal = "PASS" if ratio >= 4.5 else "FAIL"
    aa_large = "PASS" if ratio >= 3.0 else "FAIL"
    aaa_normal = "PASS" if ratio >= 7.0 else "FAIL"
    return (
        f"Contrast ratio: {ratio:.2f}:1\n"
        f"AA normal text (4.5:1): {aa_normal}\n"
        f"AA large text (3.0:1): {aa_large}\n"
        f"AAA normal text (7.0:1): {aaa_normal}"
    )
