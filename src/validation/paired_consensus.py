"""Independent raw-ballot reconstruction for the paired-prefix study.

This module does not use the producer's scoring, institutional aggregation or
backtest helpers. Its only project import is the canonical evidence primitive.
The analysis is descriptive simulator-local evidence. Logical missing-outcome
bounds are not confidence intervals, and hash checks do not audit semantic
preference leakage in a prompt.
"""

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
import hashlib
import json
from itertools import combinations
from math import sqrt
from pathlib import Path
from statistics import mean, variance
from typing import Any

from src.infra.evidence import canonical_json, content_hash, file_hash, safe_component


# The defaults document this version's action ontology. Frozen studies must
# supply their own feasible labels; these defaults are not inferred from votes.
DEFAULT_RATE_ACTIONS = (-50, -25, 0, 25, 35, 40, 50)
DEFAULT_STANCES = ("withdrawal_of_accommodation", "neutral", "accommodative")
CONDITIONS = ("H", "B", "N")
IDENTITY_FIELDS = ("branch_id", "prefix_id", "experiment_id", "meeting_date",
                   "replicate_id", "condition", "branch_draw_id")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _text(value: Any, field: str) -> str:
    _require(type(value) is str and bool(value.strip()), f"{field} must be nonempty text")
    _require(value == value.strip(), f"{field} must not contain surrounding whitespace")
    return value


def _sequence(value: Any, field: str) -> list:
    _require(isinstance(value, Sequence) and not isinstance(value, (str, bytes)),
             f"{field} must be a sequence")
    return list(value)


def _label(value: Any) -> tuple[int, str]:
    _require(isinstance(value, Mapping), "Action label must be a mapping")
    _require(set(value) == {"vote", "stance"}, "Action label needs exactly vote and stance")
    _require(type(value["vote"]) is int, "Vote must be a finite exact integer in bps")
    return value["vote"], _text(value["stance"], "stance")


def _labels(allowed_labels: Any) -> tuple[tuple[int, str], ...]:
    labels = [_label(value) for value in _sequence(allowed_labels, "allowed_labels")]
    _require(bool(labels), "Feasible Governor action set must be nonempty")
    _require(len(labels) == len(set(labels)), "Duplicate feasible action label")
    return tuple(sorted(labels))


def _default_labels() -> list[dict]:
    return [{"vote": rate, "stance": stance}
            for rate in DEFAULT_RATE_ACTIONS for stance in DEFAULT_STANCES]


def _ballots(votes: Any, *, count: int, roster: Any = None,
             allowed_labels: Any = None) -> list[dict]:
    values = _sequence(votes, "votes")
    _require(len(values) == count, f"Expected exactly {count} raw ballots")
    feasible = set(_labels(_default_labels() if allowed_labels is None else allowed_labels))
    result = []
    for vote in values:
        _require(isinstance(vote, Mapping), "Ballot must be a mapping")
        _require(set(vote) == {"agent_id", "vote", "stance"},
                 "Raw ballot needs exactly agent_id, vote and stance")
        member = _text(vote["agent_id"], "agent_id")
        action = _label({"vote": vote["vote"], "stance": vote["stance"]})
        _require(action in feasible, "Unknown ballot rate/stance label outside feasible actions")
        result.append({"agent_id": member, "vote": action[0], "stance": action[1]})
    ids = [vote["agent_id"] for vote in result]
    _require(len(ids) == len(set(ids)), "Duplicate ballot member")
    if roster is not None:
        expected = [_text(member, "roster member") for member in _sequence(roster, "roster")]
        _require(len(expected) == count and len(set(expected)) == count, "Invalid planned roster")
        _require(set(ids) == set(expected), "Ballot identities differ from planned roster")
    return result


def ballot_metrics(votes: Any, *, roster: Any = None, allowed_labels: Any = None) -> dict:
    """Score six valid raw ballots without resolving a committee decision.

    ``vote`` is an exact integer rate change in basis points. Population SD
    describes these six rates; it is not an estimated population standard error.
    Unknown labels, duplicates and malformed ballots raise instead of scoring 0.
    """
    votes = _ballots(votes, count=6, roster=roster, allowed_labels=allowed_labels)
    pairs = list(combinations(votes, 2))
    joint = sum((left["vote"], left["stance"]) == (right["vote"], right["stance"])
                for left, right in pairs)
    rate = sum(left["vote"] == right["vote"] for left, right in pairs)
    stance = sum(left["stance"] == right["stance"] for left, right in pairs)
    rates = [vote["vote"] for vote in votes]
    average = mean(rates)
    # Integer numerator makes dispersion exactly permutation invariant before
    # the one final floating-point division and square root.
    variance_numerator = 6 * sum(rate * rate for rate in rates) - sum(rates) ** 2
    return {"n_ballots": 6, "pair_count": 15,
            "joint_agreeing_pairs": joint, "joint_agreement": joint / 15,
            "rate_agreeing_pairs": rate, "rate_agreement": rate / 15,
            "stance_agreeing_pairs": stance, "stance_agreement": stance / 15,
            "rate_mean_bps": average,
            "rate_population_sd_bps": sqrt(variance_numerator / 36),
            "rate_range_bps": max(rates) - min(rates),
            "mean_pair_absolute_rate_difference_bps": mean(
                abs(left["vote"] - right["vote"]) for left, right in pairs)}


def agreement_range(five_votes: Any, allowed_labels: Any) -> dict:
    """Enumerate attainable joint agreement for fixed peers and feasible Governor actions."""
    labels = _labels(allowed_labels)
    votes = _ballots(five_votes, count=5, allowed_labels=allowed_labels)
    counts = Counter((vote["vote"], vote["stance"]) for vote in votes)
    peer_pairs = sum(count * (count - 1) // 2 for count in counts.values())
    matches = sorted(set(counts[label] for label in labels))
    attainable = [(peer_pairs + count) / 15 for count in matches]
    width = (max(matches) - min(matches)) / 15
    return {"peer_agreeing_pairs": peer_pairs,
            "peer_joint_counts": [{"vote": label[0], "stance": label[1], "count": count}
                                  for label, count in sorted(counts.items())],
            "attainable_governor_match_counts": matches,
            "attainable_joint_agreement": attainable,
            "lower": min(attainable), "upper": max(attainable),
            "contrast_lower": -width, "contrast_upper": width}


def governor_contrast(five_votes: Any, governor_H: Any, governor_B: Any,
                      *, allowed_labels: Any = None) -> dict:
    """Return the exact B minus H numerator ``c(g_B)-c(g_H)`` and denominator 15."""
    menu = _default_labels() if allowed_labels is None else allowed_labels
    votes = _ballots(five_votes, count=5, allowed_labels=menu)
    feasible = set(_labels(menu))
    first, second = _label(governor_H), _label(governor_B)
    _require(first in feasible and second in feasible, "Unknown Governor action")
    counts = Counter((vote["vote"], vote["stance"]) for vote in votes)
    numerator = counts[second] - counts[first]
    return {"numerator": numerator, "denominator": 15, "contrast": numerator / 15}


def enumerate_peer_partitions() -> list[dict]:
    """Hand-enumerated partitions of five peers, including an unchosen action.

    These are measurement ceilings, not assumptions about how an LLM chooses.
    A frozen menu with no unchosen action can have a narrower range; use
    :func:`agreement_range` for that actual menu.
    """
    partitions = ((5,), (4, 1), (3, 2), (3, 1, 1), (2, 2, 1),
                  (2, 1, 1, 1), (1, 1, 1, 1, 1))
    return [{"partition": list(partition),
             "peer_agreeing_pairs": sum(count * (count - 1) // 2 for count in partition),
             "contrast_lower": -max(partition) / 15,
             "contrast_upper": max(partition) / 15}
            for partition in partitions]


def _hash(value: Any, field: str) -> str:
    _require(type(value) is str and len(value) == 64
             and all(char in "0123456789abcdef" for char in value), f"Invalid {field}")
    return value


def _artifact(value: Any) -> dict:
    _require(isinstance(value, Mapping), "Artifact must be a mapping")
    document = dict(value)
    digest = _hash(document.get("artifact_content_hash"), "artifact_content_hash")
    payload = {key: item for key, item in document.items() if key != "artifact_content_hash"}
    _require(content_hash(payload) == digest, "Artifact content hash mismatch")
    return document


def _prefix_identity(value: Mapping) -> tuple:
    experiment = safe_component(_text(value.get("experiment_id"), "experiment_id"))
    day = _text(value.get("meeting_date"), "meeting_date")
    try:
        _require(date.fromisoformat(day).isoformat() == day, "Meeting date must be an ISO calendar day")
    except ValueError as exc:
        raise ValueError("Meeting date must be an ISO calendar day") from exc
    replicate = value.get("replicate_id")
    _require(type(replicate) is int and replicate > 0, "Replicate must be a positive exact integer")
    expected = "prefix_" + content_hash({"experiment_id": experiment, "meeting_date": day,
                                         "replicate_id": replicate})[:24]
    _require(value.get("prefix_id") == expected, "Noncanonical prefix identity")
    return experiment, day, replicate, expected


def _branch_identity(value: Mapping) -> tuple:
    _require(isinstance(value, Mapping), "Planned branch must be a mapping")
    prefix = _prefix_identity(value)
    condition = value.get("condition")
    _require(condition in CONDITIONS, "Unknown branch condition")
    draw = safe_component(_text(value.get("branch_draw_id"), "branch_draw_id"))
    expected = "branch_" + content_hash({"prefix_id": prefix[3], "condition": condition,
                                         "branch_draw_id": draw})[:24]
    _require(value.get("branch_id") == expected, "Noncanonical branch identity")
    if "condition_id" in value:
        _require(value["condition_id"] == f"branch_{condition}_draw_{draw}", "Noncanonical branch condition identity")
    return (*prefix, draw, condition, expected)


def _prefix_votes(prefix: dict, allowed_labels: Any) -> tuple[list, list, str]:
    _require(prefix.get("status") == "complete", "Retained prefix must be complete")
    roster = [_text(member, "roster member") for member in _sequence(prefix.get("roster_ids"), "roster_ids")]
    _require(len(roster) == 6 and len(set(roster)) == 6, "Prefix must retain six distinct roster IDs")
    governor = _text(prefix.get("governor_id"), "governor_id")
    _require(governor in roster, "Governor must belong to retained roster")
    if "allowed_labels" in prefix:
        _require(_labels(prefix["allowed_labels"]) == _labels(allowed_labels),
                 "Prefix action menu differs from frozen feasible action set")
    peers = _ballots(prefix.get("non_governor_votes"), count=5,
                     roster=[member for member in roster if member != governor],
                     allowed_labels=allowed_labels)
    if "outputs" in prefix or "output_hashes" in prefix:
        outputs, hashes = prefix.get("outputs"), prefix.get("output_hashes")
        _require(isinstance(outputs, Mapping) and set(outputs) == {"1", "2", "3", "4"},
                 "Retained prefix round outputs incomplete")
        _require(isinstance(hashes, Mapping), "Retained prefix output hashes missing")
        keys = set()
        feasible = set(_labels(allowed_labels))
        for number in (1, 2, 3, 4):
            members = set(roster) - ({governor} if number == 4 else set())
            rows = outputs[str(number)]
            _require(isinstance(rows, Mapping) and set(rows) == members, "Retained prefix round roster differs")
            for member, payload in rows.items():
                _require(isinstance(payload, Mapping) and payload.get("member_id") == member,
                         "Retained raw output member identity differs")
                _require(payload.get("fallback_triggered", False) is False, "Heuristic fallback cannot be accepted")
                if number == 1:
                    action = {"vote": payload.get("proposed_rate_change_bps"), "stance": payload.get("proposed_stance")}
                elif number in (2, 3):
                    _require(type(payload.get("round_number")) is int and payload["round_number"] == number,
                             "Retained deliberation round identity differs")
                    action = {"vote": payload.get("current_rate_preference_bps"), "stance": payload.get("current_stance_preference")}
                else:
                    action = {"vote": payload.get("final_rate_vote_bps"), "stance": payload.get("final_stance_vote")}
                _require(_label(action) in feasible, "Retained raw output action outside frozen menu")
                key = f"{member}:round_{number}"
                keys.add(key)
                _require(_hash(hashes.get(key), "output_hash") == content_hash(payload),
                         "Retained raw output hash mismatch")
        _require(set(hashes) == keys, "Retained raw output hash roster differs")
        projected = _raw_final_projection(list(outputs["4"].values()), allowed_labels)
        _require({v["agent_id"]: v for v in projected} == {v["agent_id"]: v for v in peers},
                 "Prefix ballot projection differs from retained raw output")
    return peers, roster, governor


def _raw_final_projection(values: Any, allowed_labels: Any) -> list[dict]:
    result = []
    for payload in _sequence(values, "member_votes"):
        _require(isinstance(payload, Mapping), "Retained member vote must be a mapping")
        _require(payload.get("fallback_triggered", False) is False, "Heuristic fallback cannot be accepted")
        result.append({"agent_id": payload.get("member_id"), "vote": payload.get("final_rate_vote_bps"),
                       "stance": payload.get("final_stance_vote")})
    return _ballots(result, count=len(result), allowed_labels=allowed_labels)


def _average(records: list[dict], field: str) -> float | None:
    values = [record[field] for record in records if record[field] is not None]
    return mean(values) if values else None


def analyze_pairs(planned: Any, prefixes: Any, branches: Any, *,
                  allowed_labels: Any, contrast: tuple[str, str] = ("B", "H")) -> dict:
    """Reconstruct a declared contrast from retained JSON artifacts.

    ``planned`` is the entire branch schedule, including failed/unattempted IDs.
    Its entries carry the seven IDENTITY_FIELDS; prefix_hash is optional before
    generation but, if supplied, must match the retained artifact. Prefix/branch
    artifacts use the paired-prefix-v1 canonical IDs and artifact_content_hash.
    Prefixes retain ``roster_ids``, ``governor_id``, ``non_governor_votes`` and a
    feasible action menu; complete branches retain ``votes``. There must be one
    planned branch in each contrasted condition per prefix/draw. Extra artifacts,
    crossed IDs, changed peers and invalid successful ballots fail closed.

    Means average planned draws within prefix, prefixes within meeting, and
    meetings equally. Success-only means follow that hierarchy after excluding
    missing observations and are explicitly a sensitivity estimate. Missing
    prefix bounds use the global feasible-action contrast; retained peers give
    sharper ranges. No prompt semantic validation is inferred here.
    """
    menu = [{"vote": vote, "stance": stance} for vote, stance in _labels(allowed_labels)]
    _require(isinstance(contrast, (tuple, list)) and len(contrast) == 2
             and contrast[0] in CONDITIONS and contrast[1] in CONDITIONS
             and contrast[0] != contrast[1], "Contrast must name two distinct H/B/N conditions")
    positive, negative = contrast
    schedule = _sequence(planned, "planned")
    _require(bool(schedule), "Planned branch schedule must be nonempty")
    expected = {}
    pairs = defaultdict(dict)
    prefix_plans = {}
    for record in schedule:
        identity = _branch_identity(record)
        branch_id, prefix_id = identity[-1], identity[3]
        _require(branch_id not in expected, "Duplicate planned branch identity")
        expected[branch_id] = dict(record)
        prefix_plans[prefix_id] = identity[:4]
        if record["condition"] in (positive, negative):
            pairs[(prefix_id, record["branch_draw_id"])][record["condition"]] = branch_id
        if "prefix_hash" in record:
            _hash(record["prefix_hash"], "planned prefix_hash")
    _require(len({identity[0] for identity in prefix_plans.values()}) == 1,
             "Analysis must contain one experiment; refusing crossed experiments")
    _require(bool(pairs) and all(set(pair) == {positive, negative} for pair in pairs.values()),
             "Every planned contrast draw must schedule both conditions")
    _require(set(prefix_plans) == {key[0] for key in pairs},
             "Every planned prefix must include the declared contrast")
    prefix_map, peer_map = {}, {}
    for value in _sequence(prefixes, "prefixes"):
        prefix = _artifact(value)
        if "artifact_version" in prefix:
            _require(prefix["artifact_version"] == "actual-paired-prefix-v1", "Unsupported retained prefix version")
        identity = _prefix_identity(prefix)
        prefix_id = identity[3]
        _require(prefix_id in prefix_plans, "Unplanned retained prefix")
        _require(prefix_id not in prefix_map, "Duplicate retained prefix")
        _require(identity == prefix_plans[prefix_id], "Crossed retained prefix identity")
        peer_map[prefix_id] = _prefix_votes(prefix, menu)
        prefix_map[prefix_id] = prefix
    for record in expected.values():
        if "prefix_hash" in record and record["prefix_id"] in prefix_map:
            _require(record["prefix_hash"] == prefix_map[record["prefix_id"]]["artifact_content_hash"],
                     "Planned prefix hash differs from retained prefix")
    branch_map, scores = {}, {}
    for value in _sequence(branches, "branches"):
        branch = _artifact(value)
        if "artifact_version" in branch:
            _require(branch["artifact_version"] == "governor-final-information-v1", "Unsupported retained branch version")
        _branch_identity(branch)
        branch_id = branch["branch_id"]
        _require(branch_id in expected, "Unplanned retained branch")
        _require(branch_id not in branch_map, "Duplicate retained branch")
        _require(all(branch.get(key) == expected[branch_id].get(key) for key in IDENTITY_FIELDS),
                 "Branch identity differs from planned schedule")
        prefix_id = branch["prefix_id"]
        _require(prefix_id in prefix_map, "Retained branch has no retained prefix")
        _require(_hash(branch.get("prefix_hash"), "prefix_hash")
                 == prefix_map[prefix_id]["artifact_content_hash"], "Branch prefix hash mismatch")
        _require(branch.get("roster_ids") == prefix_map[prefix_id]["roster_ids"]
                 and branch.get("governor_id") == prefix_map[prefix_id]["governor_id"],
                 "Branch roster/Governor differs from retained prefix")
        _require(branch.get("status") in ("complete", "failed"), "Unknown branch status")
        if branch["status"] == "complete":
            peers, roster, governor = peer_map[prefix_id]
            votes = _ballots(branch.get("votes"), count=6, roster=roster, allowed_labels=menu)
            branch_peers = {vote["agent_id"]: vote for vote in votes if vote["agent_id"] != governor}
            _require(branch_peers == {vote["agent_id"]: vote for vote in peers},
                     "Branch changed retained peer choices")
            if "member_votes" in branch or "governor_output_hash" in branch:
                raw_votes = _raw_final_projection(branch.get("member_votes"), menu)
                _require({vote["agent_id"]: vote for vote in raw_votes} == {vote["agent_id"]: vote for vote in votes},
                         "Branch ballot projection differs from retained raw output")
                raw_governor = next(payload for payload in branch["member_votes"] if payload["member_id"] == governor)
                _require(_hash(branch.get("governor_output_hash"), "governor_output_hash") == content_hash(raw_governor),
                         "Governor output hash mismatch")
                if "outputs" in prefix_map[prefix_id]:
                    _require({payload["member_id"]: payload for payload in branch["member_votes"] if payload["member_id"] != governor}
                             == prefix_map[prefix_id]["outputs"]["4"], "Branch changed retained raw peer outputs")
            scores[branch_id] = ballot_metrics(votes, roster=roster, allowed_labels=menu)
        else:
            _require(branch.get("votes") in (None, []), "Failed branch cannot contain accepted six-ballot outcome")
        branch_map[branch_id] = branch
    condition_counts = {}
    for condition in CONDITIONS:
        ids = [branch_id for branch_id, record in expected.items() if record["condition"] == condition]
        condition_counts[condition] = {"planned": len(ids),
            "complete": sum(branch_id in scores for branch_id in ids),
            "failed": sum(branch_id in branch_map and branch_map[branch_id]["status"] == "failed" for branch_id in ids),
            "unattempted": sum(branch_id not in branch_map for branch_id in ids)}
    pair_results = []
    for (prefix_id, draw), conditions in sorted(pairs.items()):
        pos, neg = conditions[positive], conditions[negative]
        observed_pos = scores.get(pos, {}).get("joint_agreement")
        observed_neg = scores.get(neg, {}).get("joint_agreement")
        if prefix_id in prefix_map:
            bounds = agreement_range(peer_map[prefix_id][0], menu)
            pos_range = (observed_pos, observed_pos) if observed_pos is not None else (bounds["lower"], bounds["upper"])
            neg_range = (observed_neg, observed_neg) if observed_neg is not None else (bounds["lower"], bounds["upper"])
            lower, upper = pos_range[0] - neg_range[1], pos_range[1] - neg_range[0]
            source = "retained_peer_attainable_actions"
        else:
            width = 1 / 3 if len(menu) > 1 else 0.0
            lower, upper = -width, width
            source = "unobserved_prefix_global_feasible_actions"
        complete = observed_pos is not None and observed_neg is not None
        effect = observed_pos - observed_neg if complete else None
        if complete:
            governor = peer_map[prefix_id][2]
            governors = []
            for branch_id in (neg, pos):
                vote = next(vote for vote in branch_map[branch_id]["votes"] if vote["agent_id"] == governor)
                governors.append({"vote": vote["vote"], "stance": vote["stance"]})
            exact = governor_contrast(peer_map[prefix_id][0], *governors, allowed_labels=menu)
            _require(abs(effect - exact["contrast"]) < 1e-12, "Independent Governor contrast disagrees with ballot reconstruction")
            effect = lower = upper = exact["contrast"]
        pair_results.append({"prefix_id": prefix_id, "meeting_date": prefix_plans[prefix_id][1],
            "replicate_id": prefix_plans[prefix_id][2], "branch_draw_id": draw,
            "positive_branch_id": pos, "negative_branch_id": neg,
            "complete": complete, "joint_agreement_difference": effect,
            "rate_agreement_difference": scores[pos]["rate_agreement"] - scores[neg]["rate_agreement"] if complete else None,
            "stance_agreement_difference": scores[pos]["stance_agreement"] - scores[neg]["stance_agreement"] if complete else None,
            "rate_population_sd_difference_bps": scores[pos]["rate_population_sd_bps"] - scores[neg]["rate_population_sd_bps"] if complete else None,
            "lower": lower, "upper": upper, "bound_source": source})
    grouped = defaultdict(list)
    for record in pair_results:
        grouped[record["prefix_id"]].append(record)
    prefix_results = []
    for prefix_id, records in sorted(grouped.items()):
        complete = all(record["complete"] for record in records)
        prefix_results.append({"prefix_id": prefix_id, "meeting_date": records[0]["meeting_date"],
            "planned_draws": len(records), "complete_pairs": sum(record["complete"] for record in records),
            "all_planned_point": _average(records, "joint_agreement_difference") if complete else None,
            "successful_pair_sensitivity": _average(records, "joint_agreement_difference"),
            "lower": mean(record["lower"] for record in records),
            "upper": mean(record["upper"] for record in records)})
    meetings = defaultdict(list)
    for record in prefix_results:
        meetings[record["meeting_date"]].append(record)
    meeting_results = []
    for day, records in sorted(meetings.items()):
        complete = all(record["all_planned_point"] is not None for record in records)
        meeting_results.append({"meeting_date": day, "planned_prefixes": len(records),
            "planned_draws": sum(record["planned_draws"] for record in records),
            "complete_pairs": sum(record["complete_pairs"] for record in records),
            "all_planned_point": _average(records, "all_planned_point") if complete else None,
            "successful_pair_sensitivity": _average(records, "successful_pair_sensitivity"),
            "lower": mean(record["lower"] for record in records),
            "upper": mean(record["upper"] for record in records)})
    complete = all(record["complete"] for record in pair_results)
    n_meetings = len(meeting_results)
    governor_se = None
    prefix_se = None
    if complete and all(len(records) > 1 for records in grouped.values()):
        governor_se = sqrt(sum(variance(record["joint_agreement_difference"] for record in records)
                              / len(records) / len(meetings[records[0]["meeting_date"]]) ** 2
                              for records in grouped.values()) / n_meetings ** 2)
    if complete and all(len(records) > 1 for records in meetings.values()):
        prefix_se = sqrt(sum(variance(record["all_planned_point"] for record in records) / len(records)
                             for records in meetings.values()) / n_meetings ** 2)
    return {"analysis_version": "independent_paired_consensus_v1",
        "contrast": f"{positive}-{negative}", "endpoint": "joint_exact_rate_stance_pair_agreement",
        "weighting": "equal meetings; equal prefixes within meeting; planned draws averaged within prefix",
        "planned_branches": len(schedule), "planned_pairs": len(pair_results),
        "complete_pairs": sum(record["complete"] for record in pair_results),
        "planned_meetings": n_meetings, "planned_prefixes": len(prefix_results),
        "condition_counts": condition_counts, "branch_metrics": scores,
        "pairs": pair_results, "prefixes": prefix_results, "meetings": meeting_results,
        "all_planned_point": _average(meeting_results, "all_planned_point") if complete else None,
        "successful_pair_sensitivity": _average(meeting_results, "successful_pair_sensitivity"),
        "sensitivity_scope": "Observed complete pairs only, excluding prefixes/meetings with no complete pair; treatment-dependent failures can bias this estimate",
        "sharp_missing_outcome_bounds": {"lower": mean(record["lower"] for record in meeting_results),
            "upper": mean(record["upper"] for record in meeting_results),
            "scope": "All planned pairs; feasible Governor actions conditional on retained peers, global bounds for unobserved prefixes; logical bounds, not sampling uncertainty"},
        "uncertainty": {"conditional_governor_draw_monte_carlo_standard_error": governor_se,
            "fixed_cohort_prefix_monte_carlo_standard_error": prefix_se,
            "assumptions": "Independent Governor draws conditional on retained prefixes for the first SE; independent exchangeable generated prefixes within each fixed meeting for the second SE; neither assumption is established by artifact hashes",
            "temporal_generalization_interval": None, "precision_adequacy_verified": False,
            "scope": "Fixed cohort simulation Monte Carlo only; undefined for missing outcomes or insufficient replicates. Few prefixes give unreliable variance estimates; more draws do not add independent meetings."},
        "verification_scope": "Embedded artifact hashes, canonical identities and raw ballot consistency; external transcript bytes require reconstruct_from_artifacts. Provider provenance and accounting remain separate checks.",
        "prompt_semantic_leakage_validation": {"status": "manual_unverified",
            "scope": "Raw evidence and content hashes do not establish whether earlier arguments reveal final votes"}}


def _read_json(path_or_text: Any, *, is_path: bool = True) -> Any:
    def unique(items):
        value = {}
        for key, item in items:
            _require(key not in value, "Duplicate JSON field")
            value[key] = item
        return value

    def nonfinite(value):
        raise ValueError(f"Nonfinite JSON value: {value}")

    raw = Path(path_or_text).read_text(encoding="utf-8") if is_path else path_or_text
    value = json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)
    canonical_json(value)  # Rejects numeric overflow as well as explicit NaN/Inf.
    return value


def _validate_recorded_schema(raw: dict, schema: Any) -> None:
    """Validate retained JSON against its frozen schema without producer imports."""
    from jsonschema import Draft202012Validator, validators

    def local_references(value):
        if isinstance(value, Mapping):
            for key, item in value.items():
                if key in ("$ref", "$dynamicRef"):
                    _require(type(item) is str and item.startswith("#"), "Recorded schema cannot fetch external references")
                local_references(item)
        elif isinstance(value, list):
            for item in value:
                local_references(item)

    _require(isinstance(schema, Mapping), "Recorded schema missing")
    local_references(schema)
    try:
        Draft202012Validator.check_schema(schema)
        checker = Draft202012Validator.TYPE_CHECKER.redefine("integer", lambda _, item: type(item) is int)
        validator = validators.extend(Draft202012Validator, type_checker=checker)
        validator(schema).validate(raw)
    except Exception as exc:
        raise ValueError(f"Raw output violates independently checked recorded schema: {exc}") from exc


def _check_transcript(directory: Path, record: Any, payload: dict, expected: dict,
                      seen_requests: set, tracks: Counter, settings: dict, seed: int) -> None:
    _require(isinstance(record, Mapping), "Transcript receipt missing")
    name = f"round_{expected['round_number']}_{expected['member_id']}.json"
    _require(record.get("path") == name, "Transcript path/identity differs")
    path = (directory / name).resolve()
    _require(path.parent == directory.resolve(), "Transcript path escapes artifact directory")
    _require(file_hash(path) == _hash(record.get("sha256"), "transcript sha256"), "Transcript file hash mismatch")
    document = _artifact(_read_json(path))
    _require(document["artifact_content_hash"] == record.get("artifact_content_hash"), "Transcript receipt content hash mismatch")
    identity = document.get("artifact_identity")
    _require(isinstance(identity, Mapping), "Transcript artifact identity missing")
    for key in ("experiment_id", "condition_id", "meeting_date", "replicate_id", "member_id", "round_number"):
        _require(identity.get(key) == expected[key] and type(identity.get(key)) is type(expected[key]),
                 "Transcript artifact identity differs from planned request")
    for key, value in identity.items():
        if key in expected:
            _require(value == expected[key] and type(value) is type(expected[key]), "Crossed transcript artifact identity")
    generation = document.get("generation")
    _require(isinstance(generation, Mapping) and generation.get("validation_error") is None,
             "Missing/failed generation cannot reconstruct accepted ballots")
    request_identity = generation.get("request_identity")
    _require(isinstance(request_identity, Mapping) and all(
        request_identity.get(key) == value and type(request_identity.get(key)) is type(value)
        for key, value in expected.items()), "Generation request identity differs from planned request")
    metadata = generation.get("metadata")
    _require(isinstance(metadata, Mapping), "Generation metadata missing")
    request = _read_json(metadata.get("request_payload_json"), is_path=False)
    _require(isinstance(request, Mapping) and canonical_json(request.get("request_identity")) == canonical_json(request_identity),
             "Canonical request identity differs from generation")
    _require(metadata.get("request_hash") == content_hash(request), "Canonical request hash mismatch")
    _require(type(seed) is int, "Planned request seed must be exact integer")
    for metadata_key, frozen_value in (("provider", settings.get("provider")),
        ("requested_model", settings.get("model")), ("routed_model", settings.get("model")),
        ("temperature", settings.get("temperature")), ("model_epoch", settings.get("model_epoch")),
        ("max_output_tokens", settings.get("max_output_tokens")),
        ("parser_version", settings.get("parser_version")), ("seed", seed)):
        _require(metadata.get(metadata_key) == frozen_value and type(metadata.get(metadata_key)) is type(frozen_value),
                 f"Recorded {metadata_key} differs from frozen settings/seed")
        if metadata_key != "requested_model":
            _require(request.get(metadata_key) == frozen_value and type(request.get(metadata_key)) is type(frozen_value),
                     f"Canonical request {metadata_key} differs from frozen settings/seed")
    _require(type(metadata.get("max_output_tokens")) is int and metadata["max_output_tokens"] > 0,
             "Maximum output tokens must be a positive exact integer")
    schema = request.get("schema")
    _require(isinstance(settings.get("round_schema_hashes"), Mapping), "Frozen round schema hashes missing")
    _require(metadata.get("schema_hash") == content_hash(schema)
             == settings["round_schema_hashes"].get(str(expected["round_number"])), "Recorded schema differs from frozen round schema")
    _require(canonical_json(_read_json(metadata.get("schema_json"), is_path=False)) == canonical_json(schema),
             "Recorded schema JSON differs from canonical request")
    _require(metadata.get("prompt_hash") == content_hash({"system": request.get("system_prompt"), "user": request.get("user_prompt")}),
             "Recorded prompt hash differs from canonical request")
    request_id = _text(metadata.get("request_id"), "request_id")
    _require(request_id not in seen_requests, "Repeated request identity across independent generation records")
    seen_requests.add(request_id)
    track = metadata.get("evidence_type")
    expected_track = "mock" if settings.get("provider") == "mock" else "live_model"
    _require(track == expected_track and metadata.get("cache_replay") is False,
             "Paired reconstruction requires declared fresh mock/live evidence")
    tracks[track] += 1
    raw = generation.get("raw_text")
    _require(type(raw) is str, "Raw generation text missing")
    _require(record.get("raw_output_hash_kind") == "sha256_utf8_v1", "Unsupported/missing raw output digest convention")
    _require(hashlib.sha256(raw.encode("utf-8")).hexdigest() == _hash(record.get("raw_output_hash"), "raw_output_hash"),
             "Raw generation text hash mismatch")
    excluded = {"artifact_identity", "generation", "prompt", "artifact_content_hash"}
    retained = {key: value for key, value in document.items() if key not in excluded}
    raw_payload = _read_json(raw, is_path=False)
    _validate_recorded_schema(raw_payload, schema)
    _validate_recorded_schema(payload, schema)
    defaults = {"fallback_triggered": False, "is_internal": True,
                "dissenting_on_rate": False, "dissenting_on_stance": False, "open_to_compromise": False}
    _require(isinstance(raw_payload, Mapping) and not set(raw_payload) - set(payload), "Raw generation contains unknown fields")
    _require(all(canonical_json(value) == canonical_json(payload[key]) for key, value in raw_payload.items())
             and all(key in defaults and canonical_json(payload[key]) == canonical_json(defaults[key])
                     for key in set(payload) - set(raw_payload))
             and canonical_json(retained) == canonical_json(payload)
             and canonical_json(generation.get("parsed")) == canonical_json(payload),
             "Raw generation differs from retained parsed output")
    prompt = document.get("prompt")
    _require(isinstance(prompt, Mapping) and all(prompt.get(key) == metadata.get(key) == request.get(key)
             for key in ("system_prompt", "user_prompt")), "Prompt bytes differ from canonical request")


def reconstruct_from_artifacts(planned: Any, prefix_paths: Any, branch_paths: Any, *,
                               allowed_labels: Any, contrast: tuple[str, str] = ("B", "H")) -> dict:
    """Read retained files and verify actual response/request joins before scoring.

    Only standard-library parsing and shared evidence digests are used. This
    verifies file consistency and request identities; source eligibility,
    provider authentication, billing and blinded prompt interpretation still
    require their own audit. Mock transcripts retain their explicit mock label.
    """
    prefix_files = [Path(path).resolve() for path in _sequence(prefix_paths, "prefix_paths")]
    branch_files = [Path(path).resolve() for path in _sequence(branch_paths, "branch_paths")]
    _require(len(set(prefix_files)) == len(prefix_files) and len(set(branch_files)) == len(branch_files),
             "Duplicate artifact path")
    prefixes = [_artifact(_read_json(path)) for path in prefix_files]
    branches = [_artifact(_read_json(path)) for path in branch_files]
    # Validate the scientific joins first; no external receipt can rescue a
    # corrupt schedule, changed peer or malformed accepted ballot.
    result = analyze_pairs(planned, prefixes, branches, allowed_labels=allowed_labels, contrast=contrast)
    prefix_map = {prefix["prefix_id"]: prefix for prefix in prefixes}
    requests, tracks = set(), Counter()
    for path, prefix in zip(prefix_files, prefixes):
        _require(prefix.get("artifact_version") == "actual-paired-prefix-v1", "Unsupported retained prefix version")
        _require(prefix.get("generation_count") == 23 and type(prefix.get("generation_count")) is int,
                 "Prefix must retain exactly 23 actual generations")
        _require("outputs" in prefix and "output_hashes" in prefix, "Retained raw prefix outputs missing")
        receipts = prefix.get("transcripts")
        keys = set(prefix["output_hashes"])
        _require(isinstance(receipts, Mapping) and set(receipts) == keys, "Transcript receipt roster differs")
        _require(isinstance(prefix.get("generation_settings"), Mapping)
                 and content_hash(prefix["generation_settings"]) == prefix.get("generation_settings_hash"),
                 "Frozen generation settings hash mismatch")
        for field in ("snapshot_hash", "persona_hash", "generation_settings_hash"):
            _hash(prefix.get(field), field)
        _require(type(prefix.get("seed_base")) is int, "Frozen prefix seed base missing")
        _require(isinstance(prefix.get("seed_schedule"), Mapping) and set(prefix["seed_schedule"]) == keys,
                 "Frozen prefix seed schedule roster differs")
        for round_text, rows in prefix["outputs"].items():
            for member, payload in rows.items():
                expected = {key: prefix[key] for key in ("experiment_id", "meeting_date", "replicate_id", "prefix_id",
                                                         "snapshot_hash", "persona_hash", "generation_settings_hash")}
                expected.update(member_id=member, round_number=int(round_text), condition_id="shared_prefix")
                seed_bytes = json.dumps(["paired-member-round-v1", prefix["seed_base"], prefix["meeting_date"],
                    prefix["replicate_id"], member, int(round_text)], separators=(",", ":")).encode("utf-8")
                seed = int.from_bytes(hashlib.sha256(seed_bytes).digest()[:4], "big") & 0x7FFFFFFF
                _require(type(prefix["seed_schedule"][f"{member}:round_{round_text}"]) is int
                         and prefix["seed_schedule"][f"{member}:round_{round_text}"] == seed, "Frozen prefix seed audit differs")
                _check_transcript(path.parent, receipts[f"{member}:round_{round_text}"], payload, expected,
                                  requests, tracks, prefix["generation_settings"], seed)
    for path, branch in zip(branch_files, branches):
        _require(branch.get("artifact_version") == "governor-final-information-v1", "Unsupported retained branch version")
        if branch["status"] == "failed":
            continue
        prefix = prefix_map[branch["prefix_id"]]
        _require("member_votes" in branch and "governor_output_hash" in branch, "Retained raw branch outputs missing")
        payload = next(vote for vote in branch["member_votes"] if vote["member_id"] == prefix["governor_id"])
        expected = {key: prefix[key] for key in ("experiment_id", "meeting_date", "replicate_id", "prefix_id",
                                                 "snapshot_hash", "persona_hash", "generation_settings_hash")}
        expected.update(member_id=prefix["governor_id"], round_number=4,
                        condition_id=f"branch_{branch['condition']}_draw_{branch['branch_draw_id']}")
        expected.update({key: branch[key] for key in ("branch_id", "branch_draw_id", "prefix_hash")})
        expected["branch_condition"] = branch["condition"]
        seed = int(content_hash({"seed_base": prefix["seed_base"], "branch_id": branch["branch_id"]})[:8], 16) & 0x7FFFFFFF
        _require(type(branch.get("seed")) is int and branch["seed"] == seed, "Branch seed audit differs")
        _check_transcript(path.parent, branch.get("governor_transcript"), payload, expected,
                          requests, tracks, prefix["generation_settings"], seed)
    result["verification_scope"] = "Retained prefix/branch/transcript bytes, hashes, canonical request identities, raw/parsed ballot joins and prompt-byte consistency; provider authentication, source eligibility and billing are separate audits"
    result["reconstructed_generation_tracks"] = dict(tracks)
    result["reconstructed_generation_count"] = len(requests)
    return result
