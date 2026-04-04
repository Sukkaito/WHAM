from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.core.settings import settings
from app.db.models import ApiKeyRecord
from app.db.session import get_engine, session_scope


def _now():
    return datetime.now(timezone.utc)


def _hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def _parse_env_pairs(raw: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for chunk in raw.split(","):
        item = chunk.strip()
        if not item or ":" not in item:
            continue
        subject, api_key = item.split(":", 1)
        subject = subject.strip()
        api_key = api_key.strip()
        if not subject or not api_key:
            continue
        pairs.append((subject, api_key))
    return pairs


def _normalize_loaded_subjects(payload: object) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    if not isinstance(payload, dict):
        return result

    subjects = payload.get("subjects")
    if isinstance(subjects, dict):
        for subject, keys in subjects.items():
            if not isinstance(subject, str) or not isinstance(keys, list):
                continue
            for api_key in keys:
                if isinstance(api_key, str):
                    subject_value = subject.strip()
                    key_value = api_key.strip()
                    if subject_value and key_value:
                        result.append((subject_value, key_value))

    entries = payload.get("api_keys")
    if isinstance(entries, list):
        for row in entries:
            if not isinstance(row, dict):
                continue
            if row.get("enabled", True) is False:
                continue
            subject = row.get("subject")
            api_key = row.get("api_key")
            if isinstance(subject, str) and isinstance(api_key, str):
                subject = subject.strip()
                api_key = api_key.strip()
                if subject and api_key:
                    result.append((subject, api_key))

    return result


def _load_bootstrap_keys() -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []

    if settings.bootstrap_api_keys_file:
        path = Path(settings.bootstrap_api_keys_file)
        if path.is_file():
            try:
                with path.open("r", encoding="utf-8") as f:
                    payload = json.load(f)
                pairs.extend(_normalize_loaded_subjects(payload))
            except Exception:
                pass

    if settings.bootstrap_api_keys:
        pairs.extend(_parse_env_pairs(settings.bootstrap_api_keys))

    # Deduplicate while preserving order
    deduped: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in pairs:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def bootstrap_api_keys() -> None:
    engine = get_engine()
    if engine is None:
        return

    pairs = _load_bootstrap_keys()
    if not pairs:
        return

    with session_scope() as session:
        for subject, api_key in pairs:
            key_hash = _hash_api_key(api_key)
            stmt = select(ApiKeyRecord).where(
                ApiKeyRecord.subject == subject,
                ApiKeyRecord.key_hash == key_hash,
            )
            row = session.execute(stmt).scalar_one_or_none()
            if row is not None:
                if not row.enabled:
                    row.enabled = True
                continue

            session.add(
                ApiKeyRecord(
                    key_id=f"key_{uuid.uuid4().hex[:16]}",
                    subject=subject,
                    key_hash=key_hash,
                    key_prefix=api_key[:6],
                    enabled=True,
                    created_at=_now(),
                    last_used_at=None,
                )
            )


def verify_api_key(subject: str, api_key: str) -> bool:
    engine = get_engine()
    if engine is None:
        return False

    key_hash = _hash_api_key(api_key)
    with session_scope() as session:
        stmt = select(ApiKeyRecord).where(
            ApiKeyRecord.enabled.is_(True),
            ApiKeyRecord.subject.in_([subject, "*"]),
        )
        rows = session.execute(stmt).scalars().all()
        for row in rows:
            if secrets.compare_digest(row.key_hash, key_hash):
                row.last_used_at = _now()
                return True

    return False
