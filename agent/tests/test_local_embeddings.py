"""Tests for bridge.local_embeddings — embedding engine, cache, hash fallback."""

from __future__ import annotations

import math
import threading


from bridge.local_embeddings import (
    EMBEDDING_DIM,
    LocalEmbeddingEngine,
    _deterministic_embedding,
    _pack_embedding,
    _unpack_embedding,
    cosine_similarity,
)


class TestHashEmbedding:
    """Deterministic hash-based fallback embedding."""

    def test_correct_dimension(self):
        vec = _deterministic_embedding("hello")
        assert len(vec) == EMBEDDING_DIM

    def test_unit_normalized(self):
        vec = _deterministic_embedding("test text")
        magnitude = math.sqrt(sum(v * v for v in vec))
        assert abs(magnitude - 1.0) < 1e-5

    def test_deterministic(self):
        v1 = _deterministic_embedding("same input")
        v2 = _deterministic_embedding("same input")
        assert v1 == v2

    def test_different_inputs_different_vectors(self):
        v1 = _deterministic_embedding("hello")
        v2 = _deterministic_embedding("world")
        assert v1 != v2

    def test_custom_dimension(self):
        vec = _deterministic_embedding("test", dim=128)
        assert len(vec) == 128


class TestPackUnpack:
    """Binary packing for SQLite storage."""

    def test_roundtrip(self):
        original = [1.0, -0.5, 0.0, 0.123]
        packed = _pack_embedding(original)
        unpacked = _unpack_embedding(packed)
        for a, b in zip(original, unpacked):
            assert abs(a - b) < 1e-6

    def test_full_dimension(self):
        vec = _deterministic_embedding("test")
        packed = _pack_embedding(vec)
        assert len(packed) == EMBEDDING_DIM * 4  # float32 = 4 bytes
        unpacked = _unpack_embedding(packed)
        assert len(unpacked) == EMBEDDING_DIM


class TestCosineSimilarity:
    """Cosine similarity computation."""

    def test_identical_vectors(self):
        vec = [1.0, 0.0, 0.0]
        assert abs(cosine_similarity(vec, vec) - 1.0) < 1e-6

    def test_orthogonal_vectors(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert abs(cosine_similarity(a, b)) < 1e-6

    def test_opposite_vectors(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert abs(cosine_similarity(a, b) - (-1.0)) < 1e-6

    def test_zero_vector(self):
        assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0

    def test_same_text_high_similarity(self):
        v1 = _deterministic_embedding("hello world")
        v2 = _deterministic_embedding("hello world")
        assert cosine_similarity(v1, v2) > 0.99


class TestEmbeddingEngine:
    """LocalEmbeddingEngine with hash fallback."""

    def test_hash_backend(self, tmp_path):
        engine = LocalEmbeddingEngine(model_dir=tmp_path / "nomodel")
        vec = engine.embed("test")
        assert len(vec) == EMBEDDING_DIM
        assert engine.backend == "hash"

    def test_dimension_property(self, tmp_path):
        engine = LocalEmbeddingEngine(model_dir=tmp_path / "nomodel")
        assert engine.dimension == EMBEDDING_DIM

    def test_embed_deterministic(self, tmp_path):
        engine = LocalEmbeddingEngine(model_dir=tmp_path / "nomodel")
        v1 = engine.embed("test")
        v2 = engine.embed("test")
        assert v1 == v2

    def test_embed_batch(self, tmp_path):
        engine = LocalEmbeddingEngine(model_dir=tmp_path / "nomodel")
        texts = ["hello", "world", "foo"]
        results = engine.embed_batch(texts)
        assert len(results) == 3
        assert all(len(v) == EMBEDDING_DIM for v in results)

    def test_cache_hit(self, tmp_path):
        cache_db = tmp_path / "cache.db"
        engine = LocalEmbeddingEngine(
            model_dir=tmp_path / "nomodel",
            cache_db=cache_db,
        )
        v1 = engine.embed("cached text")
        v2 = engine.embed("cached text")
        # Float32 packing causes slight precision loss; check approximate equality
        assert len(v1) == len(v2)
        for a, b in zip(v1, v2):
            assert abs(a - b) < 1e-5

    def test_cache_invalidation(self, tmp_path):
        cache_db = tmp_path / "cache.db"
        engine = LocalEmbeddingEngine(
            model_dir=tmp_path / "nomodel",
            cache_db=cache_db,
        )
        engine.embed("text1")
        engine.embed("text2")
        removed = engine.invalidate_cache()
        assert removed == 2

    def test_close(self, tmp_path):
        engine = LocalEmbeddingEngine(
            model_dir=tmp_path / "nomodel",
            cache_db=tmp_path / "cache.db",
        )
        engine.embed("test")
        engine.close()
        assert engine._cache_conn is None

    def test_no_cache(self, tmp_path):
        engine = LocalEmbeddingEngine(model_dir=tmp_path / "nomodel")
        vec = engine.embed("no cache")
        assert len(vec) == EMBEDDING_DIM

    def test_batch_large(self, tmp_path):
        engine = LocalEmbeddingEngine(
            model_dir=tmp_path / "nomodel",
            batch_size=2,
        )
        texts = [f"text {i}" for i in range(5)]
        results = engine.embed_batch(texts)
        assert len(results) == 5


class TestBackendNameExposure:
    """Sprint 05.04 — `_backend_name` attribute + `backend_name` property
    track the three-way fallback chain (CoreML → ONNX → hash).

    Tests mock file presence to assert the chain selects the expected backend
    and that `_backend_name` matches the public `backend` value at all times.
    """

    def test_backend_name_initial_state_before_load(self, tmp_path):
        """Before _load_model() runs, both attribute aliases read 'none'."""
        engine = LocalEmbeddingEngine(model_dir=tmp_path / "empty")
        # Direct attribute access — no lazy load
        assert engine._backend == "none"
        assert engine._backend_name == "none"

    def test_hash_backend_when_no_model_files(self, tmp_path):
        """No model.onnx and no model.mlpackage → hash fallback."""
        model_dir = tmp_path / "nomodel"
        model_dir.mkdir()
        engine = LocalEmbeddingEngine(model_dir=model_dir)
        engine._load_model()
        assert engine._backend == "hash"
        assert engine._backend_name == "hash"
        assert engine.backend == "hash"
        assert engine.backend_name == "hash"

    def test_backend_name_property_lazy_loads(self, tmp_path):
        """Reading backend_name on a fresh engine triggers _load_model()."""
        model_dir = tmp_path / "nomodel"
        model_dir.mkdir()
        engine = LocalEmbeddingEngine(model_dir=model_dir)
        # Property read should drive load chain
        assert engine.backend_name == "hash"
        # And the alias attribute is populated
        assert engine._backend_name == "hash"

    def test_backend_and_backend_name_stay_in_lockstep(self, tmp_path):
        """The `_backend_name` alias mirrors `_backend` after _load_model()."""
        model_dir = tmp_path / "nomodel"
        model_dir.mkdir()
        engine = LocalEmbeddingEngine(model_dir=model_dir)
        engine._load_model()
        assert engine._backend == engine._backend_name
        assert engine.backend == engine.backend_name

    def test_onnx_backend_when_model_onnx_present(self, tmp_path, monkeypatch):
        """model.onnx present + onnxruntime mocked → backend == 'onnx'.

        Mocks the import so we don't need a real ONNX runtime in test.
        """
        model_dir = tmp_path / "withonnx"
        model_dir.mkdir()
        (model_dir / "model.onnx").write_bytes(b"\x00" * 16)  # placeholder

        # Stub out onnxruntime to avoid importing the real package.
        import sys
        import types as _types

        fake_ort = _types.ModuleType("onnxruntime")

        class _FakeSession:
            def __init__(self, path): self.path = path

        fake_ort.InferenceSession = _FakeSession  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "onnxruntime", fake_ort)

        engine = LocalEmbeddingEngine(model_dir=model_dir)
        loaded = engine._load_model()
        assert loaded is True
        assert engine._backend == "onnx"
        assert engine._backend_name == "onnx"
        assert engine.backend_name == "onnx"

    def test_coreml_backend_when_model_mlpackage_present(self, tmp_path, monkeypatch):
        """model.mlpackage present + coremltools mocked → backend == 'coreml'.

        CoreML is checked BEFORE ONNX, so this also verifies the priority
        order even when both files are present.
        """
        model_dir = tmp_path / "withcoreml"
        model_dir.mkdir()
        (model_dir / "model.mlpackage").mkdir()
        # Also drop a model.onnx to verify CoreML wins the priority race.
        (model_dir / "model.onnx").write_bytes(b"\x00" * 16)

        # Stub out coremltools.
        import sys
        import types as _types

        fake_ct = _types.ModuleType("coremltools")
        fake_ct_models = _types.ModuleType("coremltools.models")

        class _FakeMLModel:
            def __init__(self, path): self.path = path

        fake_ct_models.MLModel = _FakeMLModel  # type: ignore[attr-defined]
        fake_ct.models = fake_ct_models  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "coremltools", fake_ct)
        monkeypatch.setitem(sys.modules, "coremltools.models", fake_ct_models)

        engine = LocalEmbeddingEngine(model_dir=model_dir)
        loaded = engine._load_model()
        assert loaded is True
        assert engine._backend == "coreml"
        assert engine._backend_name == "coreml"
        assert engine.backend_name == "coreml"

    def test_fallback_to_hash_when_coreml_import_fails(self, tmp_path, monkeypatch):
        """model.mlpackage present but coremltools missing → falls through
        to ONNX, then to hash. Verifies the fallback chain handles import
        errors silently (logged, not raised).
        """
        model_dir = tmp_path / "broken"
        model_dir.mkdir()
        (model_dir / "model.mlpackage").mkdir()

        # Force coremltools import to fail
        import sys

        monkeypatch.setitem(sys.modules, "coremltools", None)

        engine = LocalEmbeddingEngine(model_dir=model_dir)
        loaded = engine._load_model()
        # No model.onnx → drops through to hash
        assert loaded is False
        assert engine._backend == "hash"
        assert engine._backend_name == "hash"


class TestCrossThreadCache:
    """Regression test for #2494 — cross-thread SQLite cache access.

    The engine is created on one thread (the main/init thread). embed() is
    then called from a worker thread. Before the fix this raised:
        ProgrammingError: SQLite objects created in a thread can only be
        used in that same thread.
    After the fix (check_same_thread=False + RLock) the cache write from the
    worker thread succeeds, and a second embed() call on the original thread
    returns a cache hit without recomputing the embedding.
    """

    def test_embed_from_worker_thread_succeeds(self, tmp_path):
        """Engine inited on main thread; embed() called from worker thread must
        not raise and must populate the cache so the next call is a cache hit.
        """
        cache_db = tmp_path / "cross_thread_cache.db"
        engine = LocalEmbeddingEngine(
            model_dir=tmp_path / "nomodel",
            cache_db=cache_db,
        )

        worker_result: list[list[float]] = []
        worker_exc: list[BaseException] = []

        def _worker() -> None:
            try:
                vec = engine.embed("cross-thread text")
                worker_result.append(vec)
            except Exception as exc:  # noqa: BLE001
                worker_exc.append(exc)

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        t.join(timeout=5)

        # Worker must have completed without error.
        assert not worker_exc, f"Worker raised: {worker_exc[0]}"
        assert len(worker_result) == 1
        assert len(worker_result[0]) == EMBEDDING_DIM

        # Second embed() on the original (main) thread must be a cache hit.
        # A cache hit returns a value with slight float32 precision loss
        # but the dimension is always exact.
        vec2 = engine.embed("cross-thread text")
        assert len(vec2) == EMBEDDING_DIM
        # Verify the values are within float32 precision of the worker result.
        for a, b in zip(worker_result[0], vec2):
            assert abs(a - b) < 1e-5, (
                "Cache miss on second embed(): cross-thread write likely failed"
            )

        engine.close()


class TestGemmaPrefixing:
    """EmbeddingGemma (#2560) task-prefix + asymmetry behavior.

    These exercise the prefix-detection and cache-key logic on the hash
    fallback (no real model file), which is enough to verify the query vs
    document asymmetry without shipping a 200MB model into the test env.
    """

    def test_gemma_detected_by_model_dir_name(self, tmp_path):
        gemma = LocalEmbeddingEngine(model_dir=tmp_path / "embeddinggemma-300m")
        arctic = LocalEmbeddingEngine(model_dir=tmp_path / "arctic-embed")
        assert gemma._is_gemma is True
        assert arctic._is_gemma is False

    def test_query_and_document_embeddings_differ_on_gemma(self, tmp_path):
        """Same text, query vs document prefix → distinct vectors."""
        engine = LocalEmbeddingEngine(model_dir=tmp_path / "embeddinggemma-300m")
        as_query = engine.embed("deploy the bridge", is_query=True)
        as_doc = engine.embed("deploy the bridge", is_query=False)
        # Asymmetric model: the two forms must not be identical.
        assert as_query != as_doc

    def test_non_gemma_ignores_is_query(self, tmp_path):
        """Arctic/hash backends embed identically regardless of is_query."""
        engine = LocalEmbeddingEngine(model_dir=tmp_path / "arctic-embed")
        as_query = engine.embed("deploy the bridge", is_query=True)
        as_doc = engine.embed("deploy the bridge", is_query=False)
        assert as_query == as_doc

    def test_default_is_document(self, tmp_path):
        """Omitting is_query == document side (the store path default)."""
        engine = LocalEmbeddingEngine(model_dir=tmp_path / "embeddinggemma-300m")
        default = engine.embed("remember this note")
        explicit_doc = engine.embed("remember this note", is_query=False)
        assert default == explicit_doc


class TestOnnxGraphResolution:
    """ONNX graph filename resolution (#2560) — supports `model.onnx` and the
    `model_quantized.onnx` export name without renaming (renaming the graph
    breaks the .onnx_data external-data reference)."""

    def _resolve(self, model_dir):
        """Mirror _load_model's graph-resolution prefix without loading."""
        from pathlib import Path
        model_path = Path(model_dir) / "model.onnx"
        if not model_path.exists() and Path(model_dir).is_dir():
            candidates = sorted(
                p for p in Path(model_dir).glob("model*.onnx")
                if not p.name.endswith(".onnx_data")
            )
            if candidates:
                model_path = candidates[0]
        return model_path

    def test_prefers_canonical_model_onnx(self, tmp_path):
        d = tmp_path / "embeddinggemma-300m"
        d.mkdir()
        (d / "model.onnx").write_bytes(b"x")
        (d / "model_quantized.onnx").write_bytes(b"x")
        assert self._resolve(d).name == "model.onnx"

    def test_falls_back_to_quantized_glob(self, tmp_path):
        d = tmp_path / "embeddinggemma-300m"
        d.mkdir()
        (d / "model_quantized.onnx").write_bytes(b"x")
        (d / "model_quantized.onnx_data").write_bytes(b"x")
        resolved = self._resolve(d)
        assert resolved.name == "model_quantized.onnx"

    def test_excludes_onnx_data_sidecar(self, tmp_path):
        d = tmp_path / "embeddinggemma-300m"
        d.mkdir()
        (d / "model_quantized.onnx_data").write_bytes(b"x")
        # Only the sidecar exists (no graph) — must not resolve to the .onnx_data.
        resolved = self._resolve(d)
        assert not resolved.name.endswith(".onnx_data")
