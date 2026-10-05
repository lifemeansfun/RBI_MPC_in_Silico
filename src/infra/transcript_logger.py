"""
Structured JSON Lines and JSON transcript logger.
Persists verbatim agent interactions for audit, reproducibility, and attribution experiments.
"""

import json
from pathlib import Path
from typing import Any, Optional
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class TranscriptLogger:
    """Manages persistence of all simulation traces."""

    def __init__(self, run_id: Optional[str] = None):
        if run_id is None:
            run_id = datetime.now().strftime("run_%Y%m%d_%H%M%S")
        self.run_id = run_id
        self.run_dir = PROJECT_ROOT / "runs" / self.run_id
        self.transcripts_dir = self.run_dir / "transcripts"
        self.transcripts_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.run_dir / "run.jsonl"

    def log_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Appends a structured event to the run log."""
        record = {
            "timestamp": datetime.now().isoformat(),
            "run_id": self.run_id,
            "event_type": event_type,
            "data": data,
        }
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def save_round_transcript(
        self,
        meeting_date: str,
        replicate_id: int,
        round_number: int,
        member_id: str,
        payload: dict[str, Any],
    ) -> Path:
        """Saves an individual agent's round output as JSON."""
        meeting_dir = self.transcripts_dir / meeting_date / f"rep_{replicate_id}"
        meeting_dir.mkdir(parents=True, exist_ok=True)
        file_path = meeting_dir / f"round_{round_number}_{member_id}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        return file_path

    def save_meeting_summary(
        self,
        meeting_date: str,
        replicate_id: int,
        summary: dict[str, Any],
    ) -> Path:
        """Saves the final committee outcome and vote tally."""
        meeting_dir = self.transcripts_dir / meeting_date / f"rep_{replicate_id}"
        meeting_dir.mkdir(parents=True, exist_ok=True)
        file_path = meeting_dir / "meeting_outcome.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
        return file_path
