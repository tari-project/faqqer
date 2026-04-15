"""Initial bulk-upload of files from the legacy faqs/ directory.

Each plain-text or markdown file becomes a document in the configured
workspace. ``.url`` files are skipped (they contain only a single URL
and are documented in the README for human reference). The script is
idempotent: a manifest in ``data_dir/kb_manifest.json`` records which
files were uploaded so re-runs do not duplicate documents.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterable, Set

from .rag_client import AnythingLLMClient, RAGError

logger = logging.getLogger(__name__)

_TEXT_SUFFIXES = {".txt", ".md", ".markdown"}


def _iter_kb_files(faq_dir: Path) -> Iterable[Path]:
    if not faq_dir.exists():
        logger.warning("FAQ directory %s does not exist; nothing to seed", faq_dir)
        return []
    return [
        p
        for p in sorted(faq_dir.rglob("*"))
        if p.is_file() and p.suffix.lower() in _TEXT_SUFFIXES
    ]


def _load_manifest(path: Path) -> Set[str]:
    if not path.exists():
        return set()
    try:
        return set(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        logger.warning("Manifest at %s is corrupt; starting from scratch", path)
        return set()


def _save_manifest(path: Path, names: Set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(names), indent=2), encoding="utf-8")


async def seed_knowledge_base(
    rag: AnythingLLMClient,
    faq_dir: Path,
    data_dir: Path,
) -> int:
    manifest_path = data_dir / "kb_manifest.json"
    uploaded = _load_manifest(manifest_path)
    files = list(_iter_kb_files(faq_dir))
    new_count = 0
    for path in files:
        key = str(path.relative_to(faq_dir))
        if key in uploaded:
            continue
        try:
            body = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.error("Could not read %s: %s", path, exc)
            continue
        try:
            await rag.upload_text_document(
                title=key, body=body, source="faqs/initial-seed"
            )
        except RAGError as exc:
            logger.error("Upload failed for %s: %s", key, exc)
            continue
        uploaded.add(key)
        new_count += 1
    _save_manifest(manifest_path, uploaded)
    logger.info(
        "KB seeding complete: %d new documents (manifest now has %d total)",
        new_count,
        len(uploaded),
    )
    return new_count
