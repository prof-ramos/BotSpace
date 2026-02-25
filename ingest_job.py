import datetime as dt
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Tuple

import faiss
import numpy as np
from huggingface_hub import HfApi, snapshot_download
from huggingface_hub._commit_api import CommitOperationAdd
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer
from tqdm import tqdm
import docx

DOCS_REPO_ID = os.getenv("DOCS_REPO_ID")
INDEX_REPO_ID = os.getenv("INDEX_REPO_ID")
DOCS_SUBDIR = os.getenv("DOCS_SUBDIR", "docs_rag")

EMBED_MODEL = os.getenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
CHUNK_CHARS = int(os.getenv("CHUNK_CHARS", "1200"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "200"))

ARTIFACTS_PREFIX = os.getenv("ARTIFACTS_PREFIX", "artifacts")
WORK_DIR = Path(os.getenv("WORK_DIR", "/tmp/rag_job"))

ALLOWED_EXTS = {".pdf", ".docx"}


def utc_iso() -> str:
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_chars(text: str, size: int, overlap: int) -> List[str]:
    text = text.strip()
    if not text:
        return []

    out: List[str] = []
    start = 0
    n = len(text)

    while start < n:
        end = min(n, start + size)
        part = text[start:end].strip()
        if part:
            out.append(part)
        if end == n:
            break
        start = max(0, end - overlap)

    return out


def parse_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    parts: List[str] = []
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        text = text.strip()
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def parse_docx(path: Path) -> str:
    document = docx.Document(str(path))
    return "\n".join(p.text for p in document.paragraphs if p.text and p.text.strip())


def parse_file(path: Path) -> Tuple[str, str]:
    ext = path.suffix.lower()
    try:
        if ext == ".pdf":
            text = parse_pdf(path)
        elif ext == ".docx":
            text = parse_docx(path)
        else:
            return "", f"unsupported_extension:{ext}"

        text = normalize(text)
        if not text:
            return "", "empty_text_after_parsing"
        return text, ""
    except Exception as exc:  # noqa: BLE001
        return "", f"{type(exc).__name__}: {exc}"


def sanitize_docs_inplace(root: Path, report_path: Path) -> None:
    cmd = [
        "python",
        "sanitize_docs.py",
        "--root",
        str(root),
        "--delete-original-doc",
        "--report",
        str(report_path),
    ]
    subprocess.run(cmd, check=True)


def create_manifest(
    docs_repo_id: str,
    docs_revision: str,
    vectors: np.ndarray,
    docs_ok_count: int,
    failures_count: int,
    chunks_count: int,
    report_path: Path,
    faiss_path: Path,
    meta_path: Path,
    failures_path: Path,
) -> Dict[str, Any]:
    return {
        "revision": "PENDING",
        "created_at": utc_iso(),
        "docs_repo_id": docs_repo_id,
        "docs_revision": docs_revision,
        "docs_subdir": DOCS_SUBDIR,
        "embed_model": EMBED_MODEL,
        "embedding_dim": int(vectors.shape[1]),
        "num_docs_ok": docs_ok_count,
        "num_docs_failed": failures_count,
        "num_chunks": chunks_count,
        "chunking": {
            "chunk_chars": CHUNK_CHARS,
            "overlap": CHUNK_OVERLAP,
        },
        "files": {
            "faiss_index": f"{ARTIFACTS_PREFIX}/faiss.index",
            "meta_json": f"{ARTIFACTS_PREFIX}/meta.json",
            "failures_json": f"{ARTIFACTS_PREFIX}/failures.json",
            "conversion_report_json": f"{ARTIFACTS_PREFIX}/conversion_report.json",
            "manifest_json": f"{ARTIFACTS_PREFIX}/manifest.json",
        },
        "checksums": {
            "faiss_sha256": sha256_file(faiss_path),
            "meta_sha256": sha256_file(meta_path),
            "conversion_report_sha256": sha256_file(report_path),
            "failures_sha256": sha256_file(failures_path),
        },
    }


def main() -> None:
    if not DOCS_REPO_ID or not INDEX_REPO_ID:
        raise RuntimeError("Defina DOCS_REPO_ID e INDEX_REPO_ID no ambiente do Job.")

    docs_dir = WORK_DIR / "docs"
    out_dir = WORK_DIR / "out" / "artifacts"
    docs_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    api = HfApi()

    print(f"[JOB] Download docs dataset: {DOCS_REPO_ID}")
    docs_local = snapshot_download(
        repo_id=DOCS_REPO_ID,
        repo_type="dataset",
        local_dir=str(docs_dir),
        local_dir_use_symlinks=False,
    )

    docs_sha = api.repo_info(DOCS_REPO_ID, repo_type="dataset").sha
    base = Path(docs_local) / DOCS_SUBDIR

    if not base.exists():
        raise RuntimeError(f"Subdir '{DOCS_SUBDIR}' não existe no dataset. Esperado: {base}")

    report_path = out_dir / "conversion_report.json"
    print(f"[JOB] Sanitizing docs at {base}")
    sanitize_docs_inplace(base, report_path)

    files = sorted(
        [p for p in base.rglob("*") if p.is_file() and p.suffix.lower() in ALLOWED_EXTS],
        key=lambda p: str(p).lower(),
    )
    print(f"[JOB] Files found after sanitize: {len(files)}")

    docs_ok: List[Dict[str, str]] = []
    failures: List[Dict[str, str]] = []

    for file_path in tqdm(files, desc="Parsing"):
        text, err = parse_file(file_path)
        rel = str(file_path.relative_to(Path(docs_local)))
        if err:
            failures.append({"path": rel, "error": err})
            continue
        docs_ok.append({"source_path": rel, "text": text})

    if not docs_ok:
        failures_path = out_dir / "failures.json"
        failures_path.write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")
        raise RuntimeError("Nenhum documento parseado com sucesso.")

    chunks: List[Dict[str, Any]] = []
    for doc_item in docs_ok:
        parts = chunk_chars(doc_item["text"], CHUNK_CHARS, CHUNK_OVERLAP)
        for i, part in enumerate(parts):
            chunks.append({
                "text": part,
                "source": doc_item["source_path"],
                "chunk_id": i,
            })

    print(f"[JOB] Parsed OK: {len(docs_ok)} | Failed: {len(failures)} | Chunks: {len(chunks)}")

    model = SentenceTransformer(EMBED_MODEL)
    vectors = model.encode(
        [chunk["text"] for chunk in chunks],
        batch_size=64,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    vectors = np.asarray(vectors, dtype="float32")

    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)

    faiss_path = out_dir / "faiss.index"
    meta_path = out_dir / "meta.json"
    failures_path = out_dir / "failures.json"
    manifest_path = out_dir / "manifest.json"

    faiss.write_index(index, str(faiss_path))
    meta_path.write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")
    failures_path.write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest = create_manifest(
        docs_repo_id=DOCS_REPO_ID,
        docs_revision=docs_sha,
        vectors=vectors,
        docs_ok_count=len(docs_ok),
        failures_count=len(failures),
        chunks_count=len(chunks),
        report_path=report_path,
        faiss_path=faiss_path,
        meta_path=meta_path,
        failures_path=failures_path,
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    ops = [
        CommitOperationAdd(
            path_in_repo=f"{ARTIFACTS_PREFIX}/faiss.index",
            path_or_fileobj=str(faiss_path),
        ),
        CommitOperationAdd(
            path_in_repo=f"{ARTIFACTS_PREFIX}/meta.json",
            path_or_fileobj=str(meta_path),
        ),
        CommitOperationAdd(
            path_in_repo=f"{ARTIFACTS_PREFIX}/failures.json",
            path_or_fileobj=str(failures_path),
        ),
        CommitOperationAdd(
            path_in_repo=f"{ARTIFACTS_PREFIX}/conversion_report.json",
            path_or_fileobj=str(report_path),
        ),
        CommitOperationAdd(
            path_in_repo=f"{ARTIFACTS_PREFIX}/manifest.json",
            path_or_fileobj=str(manifest_path),
        ),
    ]

    msg = f"reindex: {utc_iso()} docs_sha={docs_sha[:7]} chunks={len(chunks)}"
    print(f"[JOB] Publish artifacts to {INDEX_REPO_ID}")
    commit = api.create_commit(
        repo_id=INDEX_REPO_ID,
        repo_type="dataset",
        operations=ops,
        commit_message=msg,
    )

    manifest["revision"] = commit.oid
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    api.create_commit(
        repo_id=INDEX_REPO_ID,
        repo_type="dataset",
        operations=[
            CommitOperationAdd(
                path_in_repo=f"{ARTIFACTS_PREFIX}/manifest.json",
                path_or_fileobj=str(manifest_path),
            )
        ],
        commit_message=f"manifest: set revision {commit.oid[:7]}",
    )

    print(f"[JOB] Done. index_revision={commit.oid} docs_revision={docs_sha}")


if __name__ == "__main__":
    main()
