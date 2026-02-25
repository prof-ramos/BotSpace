import argparse
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List

ALLOWED_SUFFIXES = {".pdf", ".docx"}


def convert_doc_to_docx(doc_path: Path) -> Dict[str, Any]:
    """Convert .doc file to .docx using soffice headless."""
    out_dir = doc_path.parent
    target_path = doc_path.with_suffix(".docx")

    cmd = [
        "soffice",
        "--headless",
        "--convert-to",
        "docx",
        "--outdir",
        str(out_dir),
        str(doc_path),
    ]

    try:
        completed = subprocess.run(cmd, check=False, capture_output=True, text=True)
    except FileNotFoundError:
        return {
            "source": str(doc_path),
            "output": str(target_path),
            "ok": False,
            "reason": "soffice_not_found",
            "stdout": "",
            "stderr": "",
        }

    if completed.returncode != 0:
        return {
            "source": str(doc_path),
            "output": str(target_path),
            "ok": False,
            "reason": "conversion_failed",
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }

    if not target_path.exists():
        return {
            "source": str(doc_path),
            "output": str(target_path),
            "ok": False,
            "reason": "output_not_created",
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }

    return {
        "source": str(doc_path),
        "output": str(target_path),
        "ok": True,
        "reason": "converted",
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def sanitize_docs(root: Path, delete_original_doc: bool) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "root": str(root),
        "found_doc": 0,
        "converted_doc_ok": 0,
        "converted_doc_failed": 0,
        "removed_non_allowed": 0,
        "kept_files": 0,
        "conversions": [],
        "removed": [],
        "errors": [],
    }

    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"Root path not found or is not a directory: {root}")

    # 1) Convert .doc files first.
    doc_files = [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".doc"]
    report["found_doc"] = len(doc_files)

    for doc_path in doc_files:
        result = convert_doc_to_docx(doc_path)
        report["conversions"].append(result)
        if result["ok"]:
            report["converted_doc_ok"] += 1
            if delete_original_doc:
                try:
                    doc_path.unlink(missing_ok=True)
                except Exception as exc:  # noqa: BLE001
                    report["errors"].append({"path": str(doc_path), "reason": f"delete_doc_failed: {exc}"})
        else:
            report["converted_doc_failed"] += 1
            report["errors"].append({"path": str(doc_path), "reason": result["reason"]})

    # 2) Remove files that are not allowed after conversion.
    for file_path in [p for p in root.rglob("*") if p.is_file()]:
        suffix = file_path.suffix.lower()
        if suffix in ALLOWED_SUFFIXES:
            report["kept_files"] += 1
            continue

        try:
            file_path.unlink(missing_ok=True)
            report["removed_non_allowed"] += 1
            report["removed"].append({"path": str(file_path), "reason": f"suffix_not_allowed:{suffix}"})
        except Exception as exc:  # noqa: BLE001
            report["errors"].append({"path": str(file_path), "reason": f"remove_failed: {exc}"})

    # 3) Cleanup empty directories.
    for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if path.is_dir():
            try:
                if not any(path.iterdir()):
                    path.rmdir()
            except Exception:
                pass

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Sanitize docs folder: convert DOC to DOCX and keep only PDF/DOCX.")
    parser.add_argument("--root", required=True, help="Root directory to sanitize")
    parser.add_argument("--report", required=True, help="Output report JSON path")
    parser.add_argument(
        "--delete-original-doc",
        action="store_true",
        help="Delete original .doc files after successful conversion",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    report_path = Path(args.report).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)

    report = sanitize_docs(root=root, delete_original_doc=args.delete_original_doc)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
