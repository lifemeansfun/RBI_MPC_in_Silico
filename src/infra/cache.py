"""
Deterministic SQLite-backed cache for LLM API invocations.
Ensures zero re-query costs for identical prompts, models, and seeds.
"""

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class LLMCache:
    """SQLite-backed persistent response cache."""

    def __init__(self, db_path: Optional[str | Path] = None):
        if db_path is None:
            db_path = PROJECT_ROOT / ".cache" / "llm_cache.sqlite"
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS response_cache (
                    cache_key TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    system_prompt TEXT,
                    user_prompt TEXT NOT NULL,
                    temperature REAL,
                    seed INTEGER,
                    response_text TEXT NOT NULL,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_model ON response_cache(model)")

    @staticmethod
    def compute_key(
        provider: str,
        model: str,
        system_prompt: Optional[str],
        user_prompt: str,
        temperature: float,
        seed: int,
    ) -> str:
        payload = f"{provider}::{model}::{system_prompt or ''}::{user_prompt}::{temperature:.3f}::{seed}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get(self, cache_key: str) -> Optional[dict]:
        """Retrieves cached response dict if present, else None."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT response_text, input_tokens, output_tokens FROM response_cache WHERE cache_key = ?",
                (cache_key,),
            )
            row = cursor.fetchone()
            if row:
                return {
                    "response_text": row[0],
                    "input_tokens": row[1],
                    "output_tokens": row[2],
                    "cached": True,
                }
        return None

    def set(
        self,
        cache_key: str,
        provider: str,
        model: str,
        system_prompt: Optional[str],
        user_prompt: str,
        temperature: float,
        seed: int,
        response_text: str,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        """Stores LLM response in cache."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO response_cache
                (cache_key, provider, model, system_prompt, user_prompt, temperature, seed, response_text, input_tokens, output_tokens)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cache_key,
                    provider,
                    model,
                    system_prompt,
                    user_prompt,
                    temperature,
                    seed,
                    response_text,
                    input_tokens,
                    output_tokens,
                ),
            )

    def clear(self) -> None:
        """Clears all cached responses."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM response_cache")
