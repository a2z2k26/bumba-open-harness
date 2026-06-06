"""A/B harness for Mem-6 tier-aware context-window assembly (#1847).

Runs a fixed set of prompts against the bridge's ``search_knowledge`` path
in two modes:

- **Control** (flag-off): ``memory_tiers_enabled = False`` — exercises the
  legacy Branch 1 (hybrid → semantic → FTS5) path.
- **Treatment** (flag-on): ``memory_tiers_enabled = True`` — exercises
  Branch 0 (tier-aware RRF + ``assemble_context_window``).

For each prompt the harness records:

- Jaccard overlap of result ``key`` sets across control/treatment.
- Estimated token count (``len(value) // 4``) of each side.
- A 5-row preview of each side.

Writes a deterministic markdown report. Exits 0 on success; non-zero on
fixture-load / DB-open failures.

The harness is read-only: it opens the SQLite DB in read-only URI mode and
never invokes ``store_knowledge``.

Usage:
    python3 -m agent.scripts.ab_harness_memory_assembly \\
        --prompts agent/scripts/fixtures/ab_harness_prompts.jsonl \\
        --db /tmp/seeded.db \\
        --out /tmp/mem6_ab_report.md

Operator next steps documented in PR #<TBD> (Mem-6).
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import sys
from pathlib import Path
from typing import Any


def _load_prompts(path: Path) -> list[dict[str, Any]]:
    """Load JSONL prompt fixtures. Each line: ``{"prompt": "...", "tags": [...]}``."""
    if not path.exists():
        raise FileNotFoundError(f"Prompts fixture not found: {path}")
    out: list[dict[str, Any]] = []
    for lineno, raw in enumerate(path.read_text().splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{path}:{lineno} not valid JSON: {exc.msg}"
            ) from exc
    return out


def _jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard index of two sets. 1.0 = identical; 0.0 = disjoint."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _est_tokens(rows: list[dict[str, Any]]) -> int:
    """Crude token estimate: total value-length over 4."""
    total_chars = sum(len(r.get("value", "") or "") for r in rows)
    return total_chars // 4


def _preview(rows: list[dict[str, Any]], n: int = 5) -> str:
    """Render the top-N rows as a markdown sub-table."""
    if not rows:
        return "    _(no results)_"
    lines = []
    for r in rows[:n]:
        key = (r.get("key") or "")[:48]
        value = (r.get("value") or "").replace("\n", " ")[:80]
        rank = r.get("rank", 0.0)
        lines.append(f"    - `{key}` rank={rank:.4f}  · _{value}_")
    return "\n".join(lines)


async def _run_one_prompt(
    bridge_memory_mod, db_path: str, prompt: str, enabled: bool
) -> list[dict[str, Any]]:
    """Build a Memory instance with the requested flag, invoke search_knowledge."""
    from bridge.config import BridgeConfig
    from bridge.database import Database
    from bridge.hybrid_search import HybridSearch
    from bridge.local_embeddings import LocalEmbeddingEngine

    # BridgeConfig is a frozen dataclass — flag flips via replace().
    cfg = dataclasses.replace(
        BridgeConfig(),
        memory_tiers_enabled=enabled,
        # Disable WAL so the harness stays purely read-only on the DB.
        memory_wal_enabled=False,
    )

    db = Database(db_path)
    await db.connect()
    try:
        engine = LocalEmbeddingEngine(model_dir=Path("/tmp/ab-harness-noembed"))
        hybrid = HybridSearch(engine)
        memory = bridge_memory_mod.Memory(
            db=db, config=cfg, hybrid_search=hybrid,
        )
        try:
            return await memory.search_knowledge(prompt, limit=10)
        except Exception as exc:  # noqa: BLE001 — surface for the report
            return [{"key": "__error__", "value": str(exc), "rank": 0.0}]
    finally:
        await db.close()


def _render_report(
    rows: list[dict[str, Any]], prompts: list[dict[str, Any]], db_path: str
) -> str:
    """Render the full markdown report."""
    lines = [
        "# Mem-6 A/B harness report",
        "",
        f"- **DB:** `{db_path}`",
        f"- **Prompts:** {len(prompts)}",
        "- **Control:** `memory_tiers_enabled = False` (Branch 1 hybrid)",
        "- **Treatment:** `memory_tiers_enabled = True` (Branch 0 tiered)",
        "",
        "## Per-prompt summary",
        "",
        "| # | Prompt | Jaccard | Ctrl rows | Trt rows | Ctrl tokens | Trt tokens |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for i, row in enumerate(rows, start=1):
        prompt_short = (row["prompt"] or "")[:48].replace("|", "\\|")
        lines.append(
            f"| {i} | {prompt_short} | {row['jaccard']:.2f} | "
            f"{row['ctrl_count']} | {row['trt_count']} | "
            f"{row['ctrl_tokens']} | {row['trt_tokens']} |"
        )
    lines.extend(["", "## Per-prompt detail", ""])
    for i, row in enumerate(rows, start=1):
        lines.append(f"### {i}. `{row['prompt']}`")
        lines.append(f"- Jaccard overlap: **{row['jaccard']:.2f}**")
        lines.append("- Control (top 5):")
        lines.append(row["ctrl_preview"])
        lines.append("- Treatment (top 5):")
        lines.append(row["trt_preview"])
        lines.append("")
    return "\n".join(lines) + "\n"


async def _amain(args: argparse.Namespace) -> int:
    prompts = _load_prompts(Path(args.prompts))
    if not prompts:
        print("ERROR: no prompts loaded", file=sys.stderr)
        return 2

    # Lazy import — keeps `--help` cheap.
    from bridge import memory as bridge_memory_mod

    rows: list[dict[str, Any]] = []
    for entry in prompts:
        prompt = entry.get("prompt", "")
        ctrl_results = await _run_one_prompt(
            bridge_memory_mod, args.db, prompt, enabled=False
        )
        trt_results = await _run_one_prompt(
            bridge_memory_mod, args.db, prompt, enabled=True
        )
        ctrl_keys = {r["key"] for r in ctrl_results}
        trt_keys = {r["key"] for r in trt_results}
        rows.append({
            "prompt": prompt,
            "ctrl_count": len(ctrl_results),
            "trt_count": len(trt_results),
            "ctrl_tokens": _est_tokens(ctrl_results),
            "trt_tokens": _est_tokens(trt_results),
            "jaccard": _jaccard(ctrl_keys, trt_keys),
            "ctrl_preview": _preview(ctrl_results),
            "trt_preview": _preview(trt_results),
        })

    report = _render_report(rows, prompts, args.db)
    out_path = Path(args.out)
    out_path.write_text(report)
    print(f"Wrote report: {out_path}", file=sys.stderr)
    print(report)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Mem-6 A/B harness — flag-off vs flag-on memory recall."
    )
    parser.add_argument(
        "--prompts",
        required=True,
        help="Path to JSONL prompts fixture.",
    )
    parser.add_argument(
        "--db",
        required=True,
        help="Path to a (read-only or read-write) SQLite memory DB.",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Path to write the markdown report.",
    )
    args = parser.parse_args()
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    raise SystemExit(main())
