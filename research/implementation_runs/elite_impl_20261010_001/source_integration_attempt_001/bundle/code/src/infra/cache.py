"""Canonical request cache; old unprovenanced rows remain preserved and unread."""

import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

from src.infra.evidence import canonical_json, content_hash
from src.infra.exceptions import ArtifactIntegrityError

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class LLMCache:
    def __init__(self, db_path: Optional[str | Path] = None):
        self.db_path = Path(db_path) if db_path else PROJECT_ROOT / ".cache" / "llm_cache.sqlite"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""CREATE TABLE IF NOT EXISTS response_cache_v2 (
                    cache_key TEXT PRIMARY KEY, payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )""")
        except sqlite3.Error as exc:
            raise ArtifactIntegrityError("Invalid cache database") from exc

    @staticmethod
    def request_payload(provider: str, model: str, system_prompt: Optional[str],
                        user_prompt: str, temperature: float, seed: int, *,
                        max_output_tokens: int | None = None, schema: dict | None = None,
                        parser_version: str = "strict-json-v1", model_epoch: str | None = None,
                        request_identity: dict | None = None, expected_identity: dict | None = None,
                        generation_config: dict | None = None, **settings: Any) -> dict:
        return {"cache_version": 2, "provider": provider, "routed_model": model,
                "system_prompt": system_prompt, "user_prompt": user_prompt,
                "temperature": temperature, "seed": seed, "max_output_tokens": max_output_tokens,
                "schema": schema, "parser_version": parser_version, "model_epoch": model_epoch,
                "request_identity": request_identity or {}, "expected_identity": expected_identity or {},
                "generation_config": generation_config or {}, "settings": settings}

    @staticmethod
    def compute_key(provider: str, model: str, system_prompt: Optional[str],
                    user_prompt: str, temperature: float, seed: int, **settings: Any) -> str:
        return content_hash(LLMCache.request_payload(provider, model, system_prompt, user_prompt,
                                                    temperature, seed, **settings))

    def get(self, cache_key: str) -> Optional[dict]:
        try:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute("SELECT payload_json,payload_hash FROM response_cache_v2 WHERE cache_key=?", (cache_key,)).fetchone()
            if row is None:
                return None
            payload = json.loads(row[0])
            if not isinstance(payload, dict) or content_hash(payload) != row[1] or payload.get("cache_key") != cache_key:
                raise ArtifactIntegrityError("Cache content hash/identity mismatch")
            payload["cached"] = True
            return payload
        except (sqlite3.Error, ValueError, TypeError, KeyError) as exc:
            raise ArtifactIntegrityError("Corrupt cached evidence") from exc

    def set(self, cache_key: str, provider: str, model: str, system_prompt: Optional[str],
            user_prompt: str, temperature: float, seed: int, response_text: str,
            input_tokens: int, output_tokens: int, *, metadata: dict | None = None,
            request_payload: dict | None = None) -> None:
        payload = {"cache_key": cache_key, "provider": provider, "model": model,
                   "system_prompt": system_prompt, "user_prompt": user_prompt,
                   "temperature": temperature, "seed": seed, "response_text": response_text,
                   "input_tokens": input_tokens, "output_tokens": output_tokens,
                   "metadata": metadata, "request_payload": request_payload}
        raw = canonical_json(payload)
        try:
            with sqlite3.connect(self.db_path, timeout=30) as conn:
                conn.execute("PRAGMA synchronous=FULL")
                conn.execute("BEGIN IMMEDIATE")
                old = conn.execute("SELECT payload_json FROM response_cache_v2 WHERE cache_key=?", (cache_key,)).fetchone()
                if old:
                    if old[0] != raw:
                        raise ArtifactIntegrityError("Conflicting evidence for an immutable cache key")
                    return
                conn.execute("INSERT INTO response_cache_v2 (cache_key,payload_json,payload_hash) VALUES (?,?,?)", (cache_key, raw, content_hash(payload)))
        except sqlite3.Error as exc:
            raise ArtifactIntegrityError("Cache write failed") from exc

    def clear(self) -> None:
        """Explicitly clear only corrected cache rows; preserve legacy evidence."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM response_cache_v2")
