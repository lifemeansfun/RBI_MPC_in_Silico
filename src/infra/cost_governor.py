"""Durable pre-submission budget accounting, with conservative unresolved charges.

Costs are estimates at a versioned public tariff, not authenticated invoices.
Only text-only Gemini Standard calls without tools are supported by this tariff.
"""

import json
import math
import os
import socket
import sqlite3
import tempfile
import uuid
from contextlib import contextmanager
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
from typing import Optional

from src.infra.evidence import canonical_json, write_immutable
from src.infra.exceptions import (
    ArtifactIntegrityError, BudgetExceededError, BudgetLedgerError, GenerationProvenanceError,
    UncertainChargeError, UnknownPriceError,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PRICE_REVISION = "google-gemini-standard-text-2026-10-05"
PRICE_SOURCE = "https://ai.google.dev/gemini-api/docs/pricing#gemini-3.1-flash-lite"
# Verified from Google's Gemini Developer API pricing, Standard, 2026-10-05.
TOKEN_RATES_PER_MILLION = {
    "gemini-3.1-flash-lite": {"input": 0.25, "output": 1.50},
    "mock": {"input": 0.0, "output": 0.0},
}
_NANO = Decimal(1_000_000_000)


def _tokens(value: int, label: str, *, positive: bool = False) -> int:
    if type(value) is not int or value < (1 if positive else 0):
        raise GenerationProvenanceError(f"{label} must be a {'positive' if positive else 'nonnegative'} integer")
    return value


def _nanos(value: float) -> int:
    if not math.isfinite(value) or value < 0:
        raise BudgetLedgerError("Budget/cost must be finite and nonnegative")
    return int((Decimal(str(value)) * _NANO).to_integral_value(rounding=ROUND_CEILING))


def _cost_nanos(model: str, input_tokens: int, output_tokens: int) -> int:
    if model not in TOKEN_RATES_PER_MILLION:
        raise UnknownPriceError(f"No verified price for model {model!r}")
    rates = TOKEN_RATES_PER_MILLION[model]
    value = (Decimal(input_tokens) * Decimal(str(rates["input"]))
             + Decimal(output_tokens) * Decimal(str(rates["output"]))) / Decimal(1_000_000)
    return int((value * _NANO).to_integral_value(rounding=ROUND_CEILING))


class CostGovernor:
    """SQLite transactions share one hard cap across threads and processes.

    Pass a study-specific ledger_path in research. The no-path constructor creates
    an isolated durable temporary ledger for backwards-compatible component use.
    get_governor() instead selects the shared corrected-study default path.
    """

    def __init__(self, budget_cap_usd: float = 25.0, ledger_path: str | Path | None = None):
        self.budget_cap_usd = budget_cap_usd
        self._cap_nanos = _nanos(budget_cap_usd)
        self.ledger_path = Path(ledger_path) if ledger_path is not None else (
            Path(tempfile.mkdtemp(prefix="rbi-budget-")) / "budget.sqlite"
        )
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialization_path = self.ledger_path.with_name(self.ledger_path.name + ".initialized.json")
        initialization = {"ledger_filename": self.ledger_path.name, "cap_nanos": self._cap_nanos, "schema_version": 1}
        previously_initialized = self.initialization_path.exists()
        if previously_initialized:
            try:
                recorded = json.loads(self.initialization_path.read_text(encoding="utf-8"))
                if canonical_json(recorded) != canonical_json(initialization) or not self.ledger_path.is_file():
                    raise BudgetLedgerError("Previously initialized ledger is missing or its identity changed; do not reset accounting")
            except (OSError, ValueError, TypeError, GenerationProvenanceError) as exc:
                raise BudgetLedgerError("Ledger initialization evidence is missing/corrupt") from exc
        self._host = socket.gethostname()
        try:
            with self._transaction() as conn:
                tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                version = conn.execute("PRAGMA user_version").fetchone()[0]
                expected_tables = {"budget_config", "reservations"}
                if (tables and not expected_tables.issubset(tables)) or (version and not expected_tables.issubset(tables)):
                    raise BudgetLedgerError("Existing ledger tables are missing; accounting cannot be reset")
                conn.execute("CREATE TABLE IF NOT EXISTS budget_config (id INTEGER PRIMARY KEY CHECK(id=1), cap_nanos INTEGER NOT NULL, schema_version INTEGER NOT NULL)")
                conn.execute("""CREATE TABLE IF NOT EXISTS reservations (
                    reservation_id TEXT PRIMARY KEY, attempt_id TEXT UNIQUE NOT NULL,
                    provider TEXT NOT NULL, model TEXT NOT NULL, price_revision TEXT NOT NULL,
                    input_bound INTEGER NOT NULL, output_bound INTEGER NOT NULL,
                    reserved_nanos INTEGER NOT NULL, actual_nanos INTEGER,
                    input_tokens INTEGER, output_tokens INTEGER, state TEXT NOT NULL,
                    reason TEXT, evidence TEXT, owner_pid INTEGER NOT NULL,
                    owner_host TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )""")
                existing = conn.execute("SELECT cap_nanos,schema_version FROM budget_config WHERE id=1").fetchone()
                if existing is None:
                    if tables or version or previously_initialized:
                        raise BudgetLedgerError("Existing ledger configuration is missing; accounting cannot be reinitialized")
                    conn.execute("INSERT INTO budget_config VALUES (1,?,1)", (self._cap_nanos,))
                    conn.execute("PRAGMA user_version=1")
                elif existing != (self._cap_nanos, 1):
                    raise BudgetLedgerError("Ledger cap/schema differs from this study; do not reset accounting")
                self._validate_rows(conn)
        except sqlite3.Error as exc:
            raise BudgetLedgerError(f"Cannot initialize accounting ledger: {self.ledger_path}") from exc
        try:
            # SQLite is committed first. Concurrent initializers publish identical
            # fsynced marker bytes; subsequent loss/truncation cannot create a new cap.
            write_immutable(self.initialization_path, initialization, replay=True)
        except (ArtifactIntegrityError, OSError) as exc:
            raise BudgetLedgerError("Cannot preserve durable ledger initialization evidence") from exc

    @contextmanager
    def _transaction(self):
        try:
            conn = sqlite3.connect(self.ledger_path, timeout=30)
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
            finally:
                conn.close()
        except sqlite3.Error as exc:
            raise BudgetLedgerError(f"Invalid/unavailable budget ledger: {self.ledger_path}") from exc

    def _validate_rows(self, conn):
        if conn.execute("PRAGMA user_version").fetchone()[0] != 1:
            raise BudgetLedgerError("Ledger schema version is missing or invalid")
        if conn.execute("SELECT cap_nanos,schema_version FROM budget_config WHERE id=1").fetchone() != (self._cap_nanos, 1):
            raise BudgetLedgerError("Ledger budget configuration was changed or removed")
        if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise BudgetLedgerError("SQLite integrity check failed")
        for row in conn.execute("SELECT provider,model,price_revision,input_bound,output_bound,reserved_nanos,actual_nanos,input_tokens,output_tokens,state,reason,evidence,owner_pid,owner_host FROM reservations"):
            provider, model, revision, ib, ob, reserved, actual, it, ot, state, reason, evidence_json, owner_pid, owner_host = row
            if revision != PRICE_REVISION or model not in TOKEN_RATES_PER_MILLION:
                raise BudgetLedgerError("Reservation has unknown model/price revision")
            if not ((provider == "gemini" and model == "gemini-3.1-flash-lite")
                    or (provider == "mock" and model == "mock")):
                raise BudgetLedgerError("Reservation has an unverified provider/model combination")
            if type(ib) is not int or ib < 0 or type(ob) is not int or ob < 1:
                raise BudgetLedgerError("Reservation bounds are corrupt")
            if reserved != _cost_nanos(model, ib, ob) or state not in {"reserved", "submitted", "uncertain", "committed", "released"}:
                raise BudgetLedgerError("Reservation accounting is corrupt")
            if state == "committed" and (type(it) is not int or it < 0 or type(ot) is not int or ot < 0 or actual != _cost_nanos(model, it, ot)):
                raise BudgetLedgerError("Committed usage accounting is corrupt")
            if state != "committed" and actual is not None:
                raise BudgetLedgerError("Unexpected uncommitted cost")
            if type(owner_pid) is not int or owner_pid <= 0 or not isinstance(owner_host, str) or not owner_host:
                raise BudgetLedgerError("Reservation owner identity is corrupt")
            if state == "committed":
                try:
                    evidence = json.loads(evidence_json)
                except (TypeError, ValueError) as exc:
                    raise BudgetLedgerError("Committed reservation lacks usage evidence") from exc
                if (not isinstance(evidence, dict) or evidence.get("input_tokens") != it
                        or type(evidence.get("input_tokens")) is not int or evidence.get("output_tokens") != ot
                        or type(evidence.get("output_tokens")) is not int):
                    raise BudgetLedgerError("Committed evidence contradicts token accounting")
                if (it > ib or ot > ob) != (reason == "provider usage exceeded reserved token bound"):
                    raise BudgetLedgerError("Committed token-bound violation record is corrupt")
            elif it is not None or ot is not None:
                raise BudgetLedgerError("Uncommitted reservation carries settled token usage")

    def _recover_dead_owners(self, conn):
        for rid, pid, host in conn.execute("SELECT reservation_id,owner_pid,owner_host FROM reservations WHERE state IN ('reserved','submitted')"):
            dead = host != self._host
            if not dead:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    dead = True
                except PermissionError:
                    pass
            if dead:
                conn.execute("UPDATE reservations SET state='uncertain',reason='owner process unavailable; submission unresolved' WHERE reservation_id=?", (rid,))

    @staticmethod
    def _used(conn):
        return conn.execute("SELECT COALESCE(SUM(CASE WHEN state='committed' THEN actual_nanos WHEN state='released' THEN 0 ELSE reserved_nanos END),0) FROM reservations").fetchone()[0]

    def assert_can_submit(self) -> None:
        # Persist orphan recovery even when its terminal error must propagate.
        with self._transaction() as conn:
            self._validate_rows(conn)
            self._recover_dead_owners(conn)
            uncertain = conn.execute("SELECT COUNT(*) FROM reservations WHERE state='uncertain'").fetchone()[0]
            exceeded = self._used(conn) > self._cap_nanos
            violated = conn.execute("SELECT 1 FROM reservations WHERE reason='provider usage exceeded reserved token bound' LIMIT 1").fetchone()
        if uncertain:
            raise UncertainChargeError("Unresolved provider charge in ledger; new submissions halted")
        if exceeded:
            raise BudgetExceededError("Persisted estimated spend exceeds the hard cap")
        if violated:
            raise GenerationProvenanceError("Persisted provider token-bound violation; new submissions halted")

    def reserve(self, attempt_id: str, provider: str, routed_model: str,
                input_token_bound: int, max_output_tokens: int,
                price_revision: str = PRICE_REVISION) -> str:
        _tokens(input_token_bound, "input_token_bound")
        _tokens(max_output_tokens, "max_output_tokens", positive=True)
        if not isinstance(attempt_id, str) or not attempt_id:
            raise GenerationProvenanceError("A unique attempt_id is required")
        if price_revision != PRICE_REVISION or not (
            (provider == "gemini" and routed_model == "gemini-3.1-flash-lite")
            or (provider == "mock" and routed_model == "mock")
        ):
            raise UnknownPriceError("Unverified provider/tariff combination")
        reserved = _cost_nanos(routed_model, input_token_bound, max_output_tokens)
        self.assert_can_submit()
        reservation_id = uuid.uuid4().hex
        with self._transaction() as conn:
            self._validate_rows(conn)
            if conn.execute("SELECT 1 FROM reservations WHERE state='uncertain' LIMIT 1").fetchone():
                raise UncertainChargeError("Unresolved provider charge; new submissions halted")
            if conn.execute("SELECT 1 FROM reservations WHERE attempt_id=?", (attempt_id,)).fetchone():
                raise BudgetLedgerError("An attempt cannot be reserved/submitted twice")
            if self._used(conn) + reserved > self._cap_nanos:
                raise BudgetExceededError(f"Reservation would exceed ${self.budget_cap_usd:.6f} hard cap")
            conn.execute("""INSERT INTO reservations
                (reservation_id,attempt_id,provider,model,price_revision,input_bound,output_bound,reserved_nanos,state,owner_pid,owner_host)
                VALUES (?,?,?,?,?,?,?,?, 'reserved',?,?)""",
                (reservation_id, attempt_id, provider, routed_model, price_revision,
                 input_token_bound, max_output_tokens, reserved, os.getpid(), self._host))
        return reservation_id

    def mark_submitted(self, reservation_id: str) -> None:
        terminal_error = None
        with self._transaction() as conn:
            self._validate_rows(conn)
            self._recover_dead_owners(conn)
            # This check and transition must share a transaction: another process
            # can acquire an uncertain charge after assert_can_submit() returned.
            if conn.execute("SELECT 1 FROM reservations WHERE state='uncertain' LIMIT 1").fetchone():
                terminal_error = UncertainChargeError("Unresolved provider charge; submission halted")
            elif self._used(conn) > self._cap_nanos:
                terminal_error = BudgetExceededError("Persisted estimated spend exceeds the hard cap")
            elif conn.execute("SELECT 1 FROM reservations WHERE reason='provider usage exceeded reserved token bound' LIMIT 1").fetchone():
                terminal_error = GenerationProvenanceError("Persisted provider token-bound violation; submission halted")
            else:
                changed = conn.execute("UPDATE reservations SET state='submitted' WHERE reservation_id=? AND state='reserved'", (reservation_id,)).rowcount
                if changed != 1:
                    raise BudgetLedgerError("Only a fresh reservation may be submitted")
        # Commit orphan recovery before propagating its terminal error.
        if terminal_error is not None:
            raise terminal_error

    def mark_uncertain(self, reservation_id: str, reason: str) -> None:
        with self._transaction() as conn:
            self._validate_rows(conn)
            changed = conn.execute("UPDATE reservations SET state='uncertain',reason=? WHERE reservation_id=? AND state IN ('reserved','submitted','uncertain')", (reason, reservation_id)).rowcount
            if changed != 1:
                raise BudgetLedgerError("Cannot mark resolved/missing reservation uncertain")

    def release(self, reservation_id: str, *, evidence: dict) -> None:
        if not evidence or evidence.get("status") not in {"not_submitted", "provider_confirmed_no_charge"} or not evidence.get("reference"):
            raise BudgetLedgerError("Release needs recorded no-submission or provider no-charge evidence")
        with self._transaction() as conn:
            self._validate_rows(conn)
            row = conn.execute("SELECT state FROM reservations WHERE reservation_id=?", (reservation_id,)).fetchone()
            if row is None or row[0] in {"committed", "released"}:
                raise BudgetLedgerError("Cannot release resolved/missing reservation")
            if evidence["status"] == "not_submitted" and row[0] != "reserved":
                raise BudgetLedgerError("Submitted request cannot be released as not_submitted")
            conn.execute("UPDATE reservations SET state='released',evidence=? WHERE reservation_id=?", (canonical_json(evidence), reservation_id))

    def commit(self, reservation_id: str, usage: dict | None = None, *, input_tokens: int | None = None, output_tokens: int | None = None) -> float:
        usage = usage or {}
        it = _tokens(usage.get("input_tokens", input_tokens), "input_tokens")
        ot = _tokens(usage.get("output_tokens", output_tokens), "output_tokens")
        violated = False
        with self._transaction() as conn:
            self._validate_rows(conn)
            row = conn.execute("SELECT model,input_bound,output_bound,state FROM reservations WHERE reservation_id=?", (reservation_id,)).fetchone()
            if row is None or row[3] != "submitted":
                raise BudgetLedgerError("Only a submitted reservation can be committed once")
            model, ib, ob, _ = row
            actual = _cost_nanos(model, it, ot)
            violated = it > ib or ot > ob
            # Keep the real reported usage even if the asserted bound was wrong.
            conn.execute("UPDATE reservations SET state='committed',actual_nanos=?,input_tokens=?,output_tokens=?,evidence=? WHERE reservation_id=?", (actual, it, ot, canonical_json({**usage, "input_tokens": it, "output_tokens": ot}), reservation_id))
            over_cap = self._used(conn) > self._cap_nanos
            if violated:
                conn.execute("UPDATE reservations SET reason='provider usage exceeded reserved token bound' WHERE reservation_id=?", (reservation_id,))
        if violated:
            raise GenerationProvenanceError("Provider usage exceeded reserved token bound; accounting retained")
        if over_cap:
            raise BudgetExceededError("Reported usage exceeded cap; accounting retained")
        return actual / 1_000_000_000

    def receipt_for(self, reservation_id: str) -> dict:
        """Return durable resolved accounting; this is not an authenticated invoice."""
        with self._transaction() as conn:
            self._validate_rows(conn)
            fields = ("reservation_id", "attempt_id", "provider", "model", "price_revision",
                      "input_bound", "output_bound", "input_tokens", "output_tokens", "actual_nanos", "evidence", "state")
            row = conn.execute(f"SELECT {','.join(fields)} FROM reservations WHERE reservation_id=?", (reservation_id,)).fetchone()
            if row is None or row[-1] != "committed":
                raise BudgetLedgerError("Cached generation lacks a resolved durable accounting receipt")
        receipt = dict(zip(fields, row))
        receipt["estimated_cost_usd"] = receipt.pop("actual_nanos") / 1_000_000_000
        receipt["evidence"] = json.loads(receipt["evidence"])
        return receipt

    def record_usage(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Legacy adapter, priced strictly; not evidence of pre-call enforcement."""
        rid = self.reserve(uuid.uuid4().hex, "gemini" if model != "mock" else "mock", model, input_tokens, max(1, output_tokens))
        self.mark_submitted(rid)
        return self.commit(rid, {"input_tokens": input_tokens, "output_tokens": output_tokens, "adapter": "legacy_post_call"})

    def get_summary(self) -> dict:
        with self._transaction() as conn:
            self._validate_rows(conn)
            call_count, it, ot, spent = conn.execute("SELECT COUNT(*),COALESCE(SUM(input_tokens),0),COALESCE(SUM(output_tokens),0),COALESCE(SUM(actual_nanos),0) FROM reservations WHERE state='committed'").fetchone()
            used = self._used(conn)
            unresolved = conn.execute("SELECT COUNT(*) FROM reservations WHERE state IN ('reserved','submitted','uncertain')").fetchone()[0]
            uncertain = conn.execute("SELECT COUNT(*) FROM reservations WHERE state='uncertain'").fetchone()[0]
            violated = conn.execute("SELECT COUNT(*) FROM reservations WHERE reason='provider usage exceeded reserved token bound'").fetchone()[0]
        return {"call_count": call_count, "total_input_tokens": it, "total_output_tokens": ot,
                "total_tokens": it + ot, "total_estimated_cost_usd": spent / 1e9,
                "reserved_and_spent_usd": used / 1e9, "budget_cap_usd": self.budget_cap_usd,
                "budget_remaining_usd": max(0, self._cap_nanos - used) / 1e9,
                "unresolved_reservations": unresolved, "uncertain_reservations": uncertain,
                "bound_violations": violated, "price_revision": PRICE_REVISION,
                "price_source": PRICE_SOURCE, "ledger_path": str(self.ledger_path)}


_DEFAULT_GOVERNOR: Optional[CostGovernor] = None


def get_governor(budget_cap_usd: float = 25.0, ledger_path: str | Path | None = None) -> CostGovernor:
    global _DEFAULT_GOVERNOR
    path = Path(ledger_path) if ledger_path else PROJECT_ROOT / ".cache" / "corrected_budget_v1.sqlite"
    if (_DEFAULT_GOVERNOR is None or _DEFAULT_GOVERNOR.ledger_path != path
            or _DEFAULT_GOVERNOR.budget_cap_usd != budget_cap_usd):
        _DEFAULT_GOVERNOR = CostGovernor(budget_cap_usd, path)
    return _DEFAULT_GOVERNOR
