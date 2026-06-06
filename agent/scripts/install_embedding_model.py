#!/usr/bin/env python3
"""Install the in-process embedding model (#2560) — EmbeddingGemma-300m ONNX.

Downloads the quantized (q8) ONNX export + tokenizer from the community mirror
`onnx-community/embeddinggemma-300m-ONNX` and lays the files out where
`bridge.local_embeddings.LocalEmbeddingEngine._load_model` expects them:

    <model_dir>/model.onnx        (the ONNX graph)
    <model_dir>/model.onnx_data   (the weights sidecar)
    <model_dir>/tokenizer.json

After running, redeploy the bridge and confirm `/healthz` reports
`embedding_backend.backend == "onnx"` (no longer "hash").

Usage (on the Mac mini, as bumba-agent):

    .venv/bin/python scripts/install_embedding_model.py \
        --model-dir data/models/embeddinggemma-300m

By default it pulls the q8 (`model_quantized`) variant — EmbeddingGemma does
NOT support fp16, and q8 (~309MB) is the right accuracy/footprint balance for
the always-on daemon on the M4 mini. Pass --variant fp32 for full precision
(~1.23GB) or --variant q4 (~197MB) for the smallest footprint.

Requires `huggingface_hub` (shipped in the `[embeddings]` optional-deps group).
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ID = "onnx-community/embeddinggemma-300m-ONNX"

# variant -> (onnx graph filename in the repo's onnx/ dir, weights sidecar)
# EmbeddingGemma does not support fp16 — q8 (model_quantized) is the default.
VARIANTS = {
    "q8": ("model_quantized.onnx", "model_quantized.onnx_data"),
    "fp32": ("model.onnx", "model.onnx_data"),
    "q4": ("model_q4.onnx", "model_q4.onnx_data"),
}

# Tokenizer files live at the repo root.
TOKENIZER_FILES = ["tokenizer.json"]


def _download(repo_id: str, filename: str, dest_dir: Path) -> Path:
    """Download one file from the HF repo into dest_dir, return its path."""
    from huggingface_hub import hf_hub_download

    local = hf_hub_download(repo_id=repo_id, filename=filename)
    target = dest_dir / Path(filename).name
    shutil.copyfile(local, target)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=Path("data/models/embeddinggemma-300m"),
        help="Destination dir (must contain 'gemma' in its name for family "
        "detection). Default: data/models/embeddinggemma-300m",
    )
    parser.add_argument(
        "--variant",
        choices=sorted(VARIANTS),
        default="q8",
        help="ONNX precision variant. Default: q8 (model_quantized, ~309MB).",
    )
    args = parser.parse_args(argv)

    if "gemma" not in args.model_dir.name.lower():
        print(
            f"ERROR: model dir name '{args.model_dir.name}' must contain 'gemma' "
            "— the engine detects the model family by dir name.",
            file=sys.stderr,
        )
        return 2

    try:
        import huggingface_hub  # noqa: F401
    except ImportError:
        print(
            "ERROR: huggingface_hub not installed. Run "
            '`pip install -e ".[embeddings]"` first.',
            file=sys.stderr,
        )
        return 2

    args.model_dir.mkdir(parents=True, exist_ok=True)
    graph_name, data_name = VARIANTS[args.variant]

    print(f"Installing EmbeddingGemma-300m ({args.variant}) → {args.model_dir}")

    # ONNX graph + weights sidecar. Do NOT rename either file: the graph
    # protobuf references its .onnx_data sidecar by name (onnxruntime's
    # external-data resolution), so renaming the pair breaks loading. The
    # engine's _load_model globs `model*.onnx`, so the export names are found
    # as-is (#2560).
    _download(REPO_ID, f"onnx/{graph_name}", args.model_dir)
    print(f"  ✓ {graph_name}")

    _download(REPO_ID, f"onnx/{data_name}", args.model_dir)
    print(f"  ✓ {data_name}")

    for tok in TOKENIZER_FILES:
        _download(REPO_ID, tok, args.model_dir)
        print(f"  ✓ {tok}")

    print(
        "\nDone. Redeploy the bridge and verify:\n"
        "  curl -sf http://localhost:8200/healthz | python3 -m json.tool "
        "| grep -A4 embedding_backend\n"
        "Expected: backend: onnx"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
