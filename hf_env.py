import os
from pathlib import Path


def _is_writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        test_file = path / ".write_test"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def configure_hf_cache(work_dir: Path) -> Path:
    """Guarantee a writable Hugging Face cache directory and export env vars."""
    candidates = []

    env_hf_home = os.getenv("HF_HOME")
    if env_hf_home:
        candidates.append(Path(env_hf_home))

    candidates.extend(
        [
            work_dir / ".huggingface",
            Path.home() / ".cache" / "huggingface",
            Path("/tmp") / ".huggingface",
        ]
    )

    for candidate in candidates:
        if _is_writable_dir(candidate):
            os.environ["HF_HOME"] = str(candidate)
            os.environ["HF_HUB_CACHE"] = str(candidate / "hub")
            return candidate

    raise RuntimeError("Não foi possível configurar diretório gravável para cache HF.")
