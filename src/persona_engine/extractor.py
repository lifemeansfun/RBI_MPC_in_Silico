"""
Persona Calibration Engine for RBI MPC In Silico.
Quantitatively analyzes historical statements from data/processed/statements/
to calibrate hawk-dove scores, stance biases, and linguistic focus vectors.
Generates verified persona YAML files under personas/2020_2024_roster/
and compiles personas/PERSONA_REVIEW.md with verbatim grounding quotes.
"""

import re
import yaml
import logging
from pathlib import Path
from typing import Optional, Any
from collections import Counter

from src.schemas.persona_schema import MemberPersona
from src.infra.exceptions import StatementParsingError

logger = logging.getLogger("rbi_mpc.persona_engine")
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Roster metadata
ROSTER_META = {
    "shaktikanta_das": {
        "name": "Shaktikanta Das",
        "role": "Governor",
        "is_internal": True,
        "tenure": "2018-12 to present",
        "default_hawk_dove": 0.15,
        "default_stance": "withdrawal_of_accommodation",
        "voting_priority": "Consensus-builder, price stability nominal anchor balanced with growth recovery",
        "biography": "Career civil servant and former Secretary of Economic Affairs. Focuses on consensus-building, systemic macro-financial stability, and managing growth-inflation trade-offs through pragmatic institutional leadership.",
    },
    "michael_patra": {
        "name": "Dr. Michael Debabrata Patra",
        "role": "Deputy Governor",
        "is_internal": True,
        "tenure": "2020-01 to present",
        "default_hawk_dove": 0.70,
        "default_stance": "withdrawal_of_accommodation",
        "voting_priority": "Uncompromising inflation hawk, vigilant against food inflation persistence and expectation unanchoring",
        "biography": "Career central banker and monetary economics scholar. Ardent defender of the inflation targeting framework. Consistently emphasizes the anchoring of inflation expectations and the dangers of second-round effects.",
    },
    "rajiv_ranjan": {
        "name": "Dr. Rajiv Ranjan",
        "role": "Executive Director",
        "is_internal": True,
        "tenure": "2022-05 to present",
        "default_hawk_dove": 0.40,
        "default_stance": "withdrawal_of_accommodation",
        "voting_priority": "Monetary transmission and banking system liquidity alignment with the policy rate",
        "biography": "Senior career RBI economist. Focuses on monetary transmission mechanisms, liquidity management, and ensuring that operating target rates align with the policy repo rate.",
    },
    "mridul_saggar": {
        "name": "Dr. Mridul K. Saggar",
        "role": "Executive Director",
        "is_internal": True,
        "tenure": "2020-10 to 2022-04",
        "default_hawk_dove": 0.20,
        "default_stance": "accommodative",
        "voting_priority": "Macro-financial linkages, orderly normalization from pandemic accommodations",
        "biography": "Macroeconomist with expertise in global spillovers and financial markets. Advocates for orderly normalization of crisis-era accommodations while protecting the nascent growth recovery.",
    },
    "jayanth_varma": {
        "name": "Prof. Jayanth R. Varma",
        "role": "External Member",
        "is_internal": False,
        "tenure": "2020-10 to 2024-10",
        "default_hawk_dove": -0.65,
        "default_stance": "neutral",
        "voting_priority": "Persistent growth defender, severe critic of excessive real interest rates and long policy lags",
        "biography": "Professor of Finance. Highly critical of excessively high real interest rates. Argues that monetary policy acts with long lags and that tight policy disproportionately harms economic growth when inflation is supply-driven.",
    },
    "ashima_goyal": {
        "name": "Dr. Ashima Goyal",
        "role": "External Member",
        "is_internal": False,
        "tenure": "2020-10 to 2024-10",
        "default_hawk_dove": -0.30,
        "default_stance": "neutral",
        "voting_priority": "Real rate targeting near neutral (1%), supply-side inflation diagnosis, post-pandemic recovery",
        "biography": "Emeritus Professor of Economics. Specializes in open-economy macroeconomics for emerging markets. Advocates that supply-side inflation should not be met with demand-crushing rate hikes, favoring a near-neutral real rate.",
    },
    "shashanka_bhide": {
        "name": "Dr. Shashanka Bhide",
        "role": "External Member",
        "is_internal": False,
        "tenure": "2020-10 to 2024-10",
        "default_hawk_dove": 0.25,
        "default_stance": "withdrawal_of_accommodation",
        "voting_priority": "Agricultural and rural economy specialist, cautious on persistent food price shocks and monsoon risks",
        "biography": "Agricultural economist. Focuses deeply on rural demand, monsoon impact on food prices, and the broader structural bottlenecks in the Indian economy.",
    },
}

HAWK_LEXICON = [
    "inflation", "restrictive", "vigilance", "unanchored", "persistence", "second-round",
    "overheating", "pressures", "brake", "firm", "committed", "tolerance", "target",
]

DOVE_LEXICON = [
    "growth", "slack", "over-tightening", "lag", "lags", "sacrifice", "soften",
    "real rate", "neutral", "output gap", "recovery", "headwind", "downturn",
]


class PersonaExtractor:
    """Deterministic lexical summaries restricted by documented publication availability.

    Lexical counts are descriptive statistics, not estimates of a structural hawk/dove
    utility. No subjective legacy priors or retrospective biographies enter this fit.
    """
    def __init__(self, statements_dir=None, output_dir=None, information_cutoff="2023-04-30", source_root=None):
        from datetime import date
        self.statements_dir = Path(statements_dir or PROJECT_ROOT / "data/processed/statements_v2")
        self.information_cutoff = date.fromisoformat(str(information_cutoff)).isoformat()
        self.output_dir = Path(output_dir or PROJECT_ROOT / "personas" / f"calibration_{self.information_cutoff}_v2")
        self.source_root = Path(source_root or PROJECT_ROOT)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._sources = {}

    def load_member_corpus(self, member_id):
        import hashlib, json
        if member_id not in ROSTER_META:
            raise ValueError(f"Unknown roster member {member_id}")
        corpus, sources = {}, []
        for folder in sorted(self.statements_dir.iterdir()):
            if not folder.is_dir() or not (folder / f"{member_id}.txt").exists():
                continue
            manifest_path = folder / "source_manifest.json"
            if not manifest_path.is_file():
                raise StatementParsingError(f"Missing publication manifest: {folder}")
            meta = json.loads(manifest_path.read_text())
            from src.schemas.macro_schema import iso_day
            publication = iso_day(meta["publication_date"])
            decision = iso_day(meta["decision_date"])
            if publication < decision or folder.name != decision:
                raise StatementParsingError(f"Inconsistent dates: {folder}")
            # Entire publication day must precede the declared cutoff.
            if publication >= self.information_cutoff:
                continue
            path = folder / f"{member_id}.txt"
            payload = path.read_bytes()
            digest = hashlib.sha256(payload).hexdigest()
            source = (self.source_root / meta["source_file"]).resolve()
            if not source.is_relative_to(self.source_root.resolve()) or not source.is_file():
                raise StatementParsingError(f"Missing source: {source}")
            if hashlib.sha256(source.read_bytes()).hexdigest() != meta["source_sha256"]:
                raise StatementParsingError(f"Changed source: {source}")
            if digest != meta["statement_sha256"].get(member_id):
                raise StatementParsingError(f"Changed statement: {path}")
            corpus[decision] = payload.decode("utf-8")
            sources.append({"decision_date": decision, "publication_date": publication,
                            "statement_file": str(path.resolve().relative_to(self.source_root.resolve())),
                            "statement_sha256": digest, "source_file": meta["source_file"],
                            "source_sha256": meta["source_sha256"], "availability_basis": meta["availability_basis"]})
        self._sources[member_id] = sources
        return corpus

    def analyze_member(self, member_id):
        corpus = self.load_member_corpus(member_id)
        meta = ROSTER_META[member_id]
        hawk_hits = dove_hits = total_words = 0
        sentences = []
        for decision, text in corpus.items():
            total_words += len(text.split())
            hawk_hits += sum(len(re.findall(r"\b" + re.escape(word) + r"\b", text, re.I)) for word in HAWK_LEXICON)
            dove_hits += sum(len(re.findall(r"\b" + re.escape(word) + r"\b", text, re.I)) for word in DOVE_LEXICON)
            candidates = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if 20 <= len(s.split()) <= 60]
            if candidates:
                sentences.append((decision, candidates[0]))
        score = (hawk_hits - dove_hits) / max(hawk_hits + dove_hits, 1)
        # Predeclared chronological spread; no hand-prior-conditioned quote selection.
        indices = sorted(set([0, len(sentences) // 2, len(sentences) - 1])) if sentences else []
        quotes = [f'"{sentences[i][1]}" ({sentences[i][0]})' for i in indices]
        return {"member_id": member_id, "name": meta["name"], "role": meta["role"],
                "is_internal": meta["is_internal"], "tenure": "Calibration corpus through " + self.information_cutoff,
                "meetings_count": len(corpus), "total_words": total_words,
                "hawk_hits": hawk_hits, "dove_hits": dove_hits, "calibrated_hawk_dove": round(score, 6),
                "stance_bias": "neutral", "voting_priority": "Evaluate supplied inflation and activity evidence under the RBI mandate.",
                "biography": None, "exemplar_quotes": quotes,
                "calibration_cutoff": self.information_cutoff, "corpus_sources": self._sources[member_id],
                "method": "unweighted lexical contrast; descriptive, not a Bayesian or preference estimate"}

    @staticmethod
    def _write_identical_or_new(path, payload):
        if path.exists():
            if path.read_bytes() != payload:
                raise FileExistsError(f"Refusing to overwrite a different frozen persona artifact: {path}")
            return
        with path.open("xb") as stream:
            stream.write(payload)

    def calibrate_and_persist_all(self):
        import hashlib, json
        summary = {member: self.analyze_member(member) for member in ROSTER_META}
        manifest = {"version": "dated-lexical-v2", "calibration_cutoff": self.information_cutoff,
                    "selection_rule": "publication day strictly precedes cutoff", "members": summary}
        encoded = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
        digest = hashlib.sha256(encoded).hexdigest()
        for member, data in summary.items():
            persona = MemberPersona(member_id=member, name=data["name"], role=data["role"],
                                    is_internal=data["is_internal"], tenure=data["tenure"],
                                    hawk_dove_score=data["calibrated_hawk_dove"], stance_bias="neutral",
                                    voting_priority=data["voting_priority"], biography=None,
                                    key_themes=data["exemplar_quotes"], calibration_cutoff=self.information_cutoff,
                                    corpus_manifest_hash=digest,
                                    provenance_status="dated_corpus" if data["meetings_count"] else "assumed")
            self._write_identical_or_new(self.output_dir / f"{member}.yaml",
                                        yaml.safe_dump(persona.model_dump(), sort_keys=True).encode())
        self._write_identical_or_new(self.output_dir / "corpus_manifest.json", encoded)
        self.generate_review_report(summary, self.output_dir / "PERSONA_REVIEW.md")
        return summary

    def generate_review_report(self, summary, review_path):
        lines = ["# Dated lexical persona evidence", "", f"Publication cutoff: {self.information_cutoff}.",
                 "Scores are corpus descriptions, not validated behavioral preferences. No legacy hand priors or biography claims are fitted.", "",
                 "| Member | Included meetings | Words | Hawk hits | Dove hits | Lexical contrast |",
                 "|---|---:|---:|---:|---:|---:|"]
        for member, data in summary.items():
            lines.append(f"| {member} | {data['meetings_count']} | {data['total_words']} | {data['hawk_hits']} | {data['dove_hits']} | {data['calibrated_hawk_dove']} |")
        self._write_identical_or_new(review_path, ("\n".join(lines) + "\n").encode())


if __name__ == "__main__":
    PersonaExtractor().calibrate_and_persist_all()
