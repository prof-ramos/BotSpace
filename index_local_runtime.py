import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

EMBED_MODEL = os.getenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
WORK_DIR = Path(os.getenv("WORK_DIR", "/data/work"))
ART_DIR = WORK_DIR / "out" / "artifacts"
RELOAD_POLL_SECONDS = int(os.getenv("RELOAD_POLL_SECONDS", "30"))


class LocalIndexRuntime:
    def __init__(self) -> None:
        self.model = SentenceTransformer(EMBED_MODEL)
        self.index: faiss.Index | None = None
        self.meta: List[Dict[str, Any]] | None = None
        self.last_mtime: float | None = None
        self.last_check = 0.0
        self._lock = threading.RLock()

    def _paths(self) -> tuple[Path, Path]:
        return (ART_DIR / "faiss.index", ART_DIR / "meta.json")

    def exists(self) -> bool:
        idx, meta = self._paths()
        return idx.exists() and meta.exists()

    def load(self) -> None:
        with self._lock:
            idx, meta = self._paths()
            self.index = faiss.read_index(str(idx))
            self.meta = json.loads(meta.read_text(encoding="utf-8"))
            self.last_mtime = idx.stat().st_mtime
            self.last_check = time.time()
            print(f"[INDEX] loaded local index from {idx}")

    def ensure_loaded(self) -> None:
        with self._lock:
            if not self.exists():
                raise RuntimeError(f"Indice nao existe em {ART_DIR}. Rode reindex primeiro.")
            if self.index is None or self.meta is None:
                self.load()

    def maybe_reload(self) -> None:
        now = time.time()
        if now - self.last_check < RELOAD_POLL_SECONDS:
            return
        self.last_check = now

        idx, _ = self._paths()
        if not idx.exists():
            return

        mtime = idx.stat().st_mtime
        if self.last_mtime is None or mtime > self.last_mtime:
            print("[INDEX] detected updated index; reloading...")
            self.load()

    def search(self, query: str, k: int = 4) -> List[Dict[str, Any]]:
        self.ensure_loaded()

        with self._lock:
            assert self.index is not None
            assert self.meta is not None

            qv = self.model.encode([query], normalize_embeddings=True)
            qv = np.asarray(qv, dtype="float32")

            scores, idxs = self.index.search(qv, k)
            out: List[Dict[str, Any]] = []
            for score, i in zip(scores[0], idxs[0]):
                if i == -1:
                    continue
                item = dict(self.meta[i])
                item["score"] = float(score)
                out.append(item)
            return out
