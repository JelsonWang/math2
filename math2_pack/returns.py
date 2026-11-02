"""Validate untrusted ChatGPT returns without inventing evidence or certificates.

This module is pure with respect to caller data and persistent state. Schemas are
loaded from the installed project. Text grades remain provisional even when a
card passes every structural and historical check.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import math
import sys
from pathlib import Path, PurePosixPath

from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas/daily_return.schema.json"
if not SCHEMA_PATH.is_file():
    SCHEMA_PATH = Path(sys.prefix) / 'share/math2_pack/schemas/daily_return.schema.json'


def load_schema():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _timestamp(value):
    if value is None:
        return None
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timezone is required")
    return parsed


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _map(values, key):
    if isinstance(values, dict):
        return values
    return {x[key]: x for x in values or []}


def validate_return(card, release, bank, state):
    """Return {errors, warnings, normalized}; never write files or modify inputs.

    `normalized` is None on rejection. REAL and SYNTHETIC_TEST_ONLY ledgers cannot
    cross. Hash/ref checks bind this card to one release and its preceding state;
    upstream import handles byte-for-byte idempotent cards before calling here.
    """
    errors, warnings = [], []

    def error(code, path, message):
        errors.append({"code": code, "path": path, "message": message})

    def warning(code, path, message):
        warnings.append({"code": code, "path": path, "message": message})

    if not isinstance(card, dict):
        error("SCHEMA", "$", "Return card must be a JSON object")
        return {"errors": errors, "warnings": warnings, "normalized": None}
    try:
        _canonical(card)
    except (ValueError, TypeError, RecursionError):
        error("NON_JSON_OR_NONFINITE", "$", "Finite JSON values are required; no NaN/Infinity")
        return {"errors": errors, "warnings": warnings, "normalized": None}
    validator = Draft202012Validator(load_schema(), format_checker=FormatChecker())
    for failure in sorted(validator.iter_errors(card), key=lambda x: str(list(x.absolute_path))):
        path = "$" + "".join(f"[{v}]" if isinstance(v, int) else "." + v for v in failure.absolute_path)
        error("SCHEMA", path, failure.message)
    # Some minimal installations omit jsonschema's optional RFC3339 checker.
    # Independently require aware ISO times before any chronology operations.
    def check_times(value, path="$"):
        if isinstance(value, dict):
            for key, entry in value.items():
                if key in {"received_at", "feedback_at", "presented_at", "started_at", "ended_at", "at"} and entry is not None:
                    try:
                        _timestamp(entry)
                    except (ValueError, TypeError, AttributeError):
                        error("TIMESTAMP", path + "." + key, "An actual timezone-aware ISO timestamp or null is required")
                check_times(entry, path + "." + key)
        elif isinstance(value, list):
            for index, entry in enumerate(value):
                check_times(entry, path + f"[{index}]")
    check_times(card)
    if isinstance(card.get("date"), str):
        try:
            dt.date.fromisoformat(card["date"])
        except ValueError:
            error("DATE", "date", "An actual ISO calendar date is required")
    if errors:
        return {"errors": errors, "warnings": warnings, "normalized": None}
    normalized = copy.deepcopy(card)
    if not any(card[k] for k in ("attempts", "presented_items", "repair_events", "retest_events")):
        error("EMPTY_RETURN_NOT_LEARNING_EVIDENCE", "$", "An empty template is not evidence of training or an adaptive update")
    if not all(isinstance(x, dict) for x in (release, state)):
        error("CONTEXT", "$", "Release and prior state must be JSON objects")
        return {"errors": errors, "warnings": warnings, "normalized": None}
    for field in ("release_id", "source_state_hash", "record_kind"):
        if card[field] != release.get(field):
            error("RELEASE_BINDING", field, "Card differs from registered release: " + field)
    if card['date']!=release.get('date'):
        if card.get('release_date')!=release.get('date') or card['date']<release.get('date',''):
            error('RELEASE_BINDING','release_date','A different actual date requires the unchanged original release_date')
        else:warning('ACTUAL_TRAINING_DATE_DIFFERS','date','Original release and state hash are preserved')
    elif card.get('release_date',release.get('date'))!=release.get('date'):
        error('RELEASE_BINDING','release_date','Original release date cannot be rewritten')
    reported=set(card.get('reported_answered_item_ids',[]))
    actual={a['item_id'] for a in card['attempts']}
    missing=reported-actual
    if card.get('submission_scope')=='COMPLETE_SESSION':
        if 'reported_answered_item_ids' not in card:
            error('COMPLETE_SCOPE_REQUIRES_ANSWER_INVENTORY','reported_answered_item_ids','Declare the actual answered inventory; planned items are not automatically attempted')
        if actual-reported:
            error('ANSWER_INVENTORY_CONFLICT','reported_answered_item_ids','Actual attempts must match the declared answered inventory')
    if missing:error('INCOMPLETE_ATTEMPT_COVERAGE','attempts','Missing first answers: '+','.join(sorted(missing)))
    if card.get('submission_scope')!='COMPLETE_SESSION':
        warning('PARTIAL_STATE_ONLY','submission_scope','Not certified as a complete session export')
    if card["record_kind"] != state.get("record_kind"):
        error("REAL_SYNTHETIC_ISOLATION", "record_kind", "Synthetic and real records cannot be mixed")
    if card["source_state_hash"] != state.get("source_state_hash"):
        if state.get('pending_audit_release_bases',{}).get(card['release_id'])==card['source_state_hash']:
            warning('AUDIT_ONLY_STATE_DELTA','source_state_hash','Only a secondary audit followed this release; original binding retained')
        else:
            error("STALE_STATE", "source_state_hash", "Return is not based on the current learning state")
    if state.get("last_training_date") and card["date"] < state["last_training_date"]:
        error("RETROACTIVE_DAILY_RETURN", "date", "A new daily return cannot silently rewrite earlier training days")
    if release.get("version") != "1.0":
        error("RELEASE_VERSION", "version", "Unsupported release contract")
    # Catalogs may use id rather than item_id; normalize keys without changing them.
    if isinstance(bank, dict):
        bank_map = bank
    elif isinstance(bank, list) and all(isinstance(x, dict) for x in bank):
        bank_map = {x.get("item_id", x.get("id")): x for x in bank}
    else:
        error("CONTEXT", "bank", "Bank must be an item map or list")
        return {"errors": errors, "warnings": warnings, "normalized": None}
    refs = _map(release.get("item_refs", []), "item_id")
    prior_attempts = _map(state.get("attempts", {}), "attempt_id")
    exposures = state.get("exposures", {})

    def reference(iid, version, path):
        item, ref = bank_map.get(iid), refs.get(iid)
        if not item or not ref:
            error("UNKNOWN_ITEM", path, "Item is absent from bank or this release")
            return None
        actual = item.get("item_version", item.get("version_hash"))
        if ref.get("item_version") != version or actual != version:
            error("ITEM_VERSION", path, "Exact bank and release version hashes are required")
        status = item.get("release_status", "")
        if status.startswith(("FROZEN", "REJECTED")):
            error("FROZEN_ITEM", path, "Frozen content cannot be represented as a delivered training item")
        return item

    seen_presentations = {}
    for index, entry in enumerate(card["presented_items"]):
        path = f"presented_items[{index}]"
        key = (entry["item_id"], entry["item_version"])
        reference(*key, path)
        if key in seen_presentations:
            error("DUPLICATE_PRESENTATION", path, "Use one conservative exposure entry per item version")
        seen_presentations[key] = entry
        if entry["exposure"] == "UNKNOWN_POSSIBLY_EXPOSED" and entry["presented_at"] is not None:
            warning("UNCERTAIN_PRESENTATION_TIME", path, "Package visibility is not proof of actual presentation")

    asset_paths = {}

    def assets(values, path):
        local = set()
        for n, asset in enumerate(values):
            name = asset["path"]
            posix = PurePosixPath(name.replace("\\", "/"))
            canonical_path = str(posix)
            reserved = {"CON", "PRN", "AUX", "NUL", *("COM" + str(v) for v in range(1, 10)), *("LPT" + str(v) for v in range(1, 10))}
            if posix.is_absolute() or ".." in posix.parts or ":" in name or name.startswith(("\\", "/")) or any(ord(c) < 32 for c in name) or any(part != part.rstrip(" .") or part.split(".")[0].upper() in reserved for part in posix.parts):
                error("UNSAFE_ASSET_PATH", f"{path}[{n}]", "Asset path must remain relative to the returned evidence bundle")
            if canonical_path in local:
                error("DUPLICATE_ASSET", path, "The same evidence page was listed more than once")
            local.add(canonical_path)
            if canonical_path in asset_paths and asset_paths[canonical_path] != asset["sha256"]:
                error("ASSET_HASH_CONFLICT", path, "One evidence path has conflicting byte hashes")
            asset_paths[canonical_path] = asset["sha256"]
            warning("ASSET_BYTES_REQUIRE_IMPORT_CHECK", path, "A hash string alone does not prove attachment bytes exist")

    attempts = {}
    attempt_item_versions = set()
    supplements = set()
    for index, attempt in enumerate(card["attempts"]):
        path = f"attempts[{index}]"
        aid, iid = attempt["attempt_id"], attempt["item_id"]
        if aid in attempts:
            error("DUPLICATE_ATTEMPT", path, "Attempt IDs cannot repeat within a return")
        item_key = (iid, attempt["item_version"])
        if item_key in attempt_item_versions:
            error("DUPLICATE_FIRST_ITEM", path, "A second ID does not create another independent first answer to the same item version")
        attempt_item_versions.add(item_key)
        attempts[aid] = attempt
        item = reference(iid, attempt["item_version"], path)
        first = attempt["first_answer"]
        assets(first["assets"], path + ".first_answer.assets")
        if not first["raw"].strip() and not first["assets"]:
            error("EMPTY_FIRST_ANSWER", path, "Preserve an actual answer, evidence page, or explicit abandonment text")
        presented = seen_presentations.get((iid, attempt["item_version"]))
        if not presented or presented["exposure"] != "CONFIRMED_SEEN":
            error("ATTEMPT_WITHOUT_PRESENTATION", path, "An actual attempt requires a confirmed presented-item event")
        prior_exposure = exposures.get(iid, {})
        prior_exposure = prior_exposure.get("state", prior_exposure.get("status")) if isinstance(prior_exposure, dict) else prior_exposure
        initial = item.get("initial_exposure") if item else None
        # An already preserved first answer retains its original pre-presentation
        # declaration when later pages are appended. That is not a new unseen claim.
        if attempt["exposure_declaration"] == "UNSEEN_SELF_DECLARED" and aid not in prior_attempts:
            if any(key != aid and row.get("item_id") == iid for key, row in prior_attempts.items()):
                error("EXPOSURE_DOWNGRADE", path, "An earlier preserved attempt proves this item has already been seen")
            if prior_exposure in ("CONFIRMED_SEEN", "UNKNOWN_POSSIBLY_EXPOSED") or initial in ("CONFIRMED_SEEN", "UNKNOWN_POSSIBLY_EXPOSED", "UNKNOWN_REQUIRES_EVIDENCE"):
                error("EXPOSURE_DOWNGRADE", path, "Known seen/uncertain exposure cannot be reset by a return assertion")
            if release.get("mode") == "COACH_BUNDLE_LIMITED" or refs.get(iid, {}).get("exposure_eligibility") == "UNKNOWN_POSSIBLY_EXPOSED":
                error("BUNDLE_NOT_UNSEEN", path, "A readable full coach bundle cannot establish strict unseen independence")
        grade = attempt["grade"]
        for dimension, observation in grade.get("dimensions", {}).items():
            if observation and any(claim in observation.upper() for claim in ("INSTRUCTOR_VERIFIED", "DELAYED_VERIFIED", "CERTIFIED_H0", "CERTIFIED_M4")):
                error("DIMENSION_CERTIFICATE", path + ".grade.dimensions." + dimension, "Dimensions record formative observations only, never verified mastery")
        max_points = item.get("max_points", item.get("max_score")) if item else None
        if max_points is not None and grade["max_points"] != max_points:
            error("MAX_POINTS", path + ".grade", "Maximum must match the released item")
        score = grade["score"]
        if score is not None and score > grade["max_points"]:
            error("SCORE_RANGE", path + ".grade.score", "Score exceeds the released maximum")
        steps = grade["step_scores"]
        step_ids = [x["step_id"] for x in steps]
        if len(step_ids) != len(set(step_ids)):
            error("DUPLICATE_GRADE_STEP", path + ".grade", "Scoring steps cannot be duplicated")
        if grade["status"] == "PENDING_HUMAN_REVIEW" and score is not None:
            error("PENDING_NOT_SCORED", path + ".grade", "Unsupported review remains unscored")
        if score is not None:
            if not steps or any(x["earned"] is None for x in steps):
                error("SCORE_WITHOUT_STEPS", path + ".grade", "A numeric formative score requires actual per-step reasoning")
            else:
                if abs(sum(x["earned"] for x in steps) - score) > 1e-6 or abs(sum(x["maximum"] for x in steps) - grade["max_points"]) > 1e-6:
                    error("RUBRIC_TOTAL", path + ".grade", "Step scores and maxima must sum to the stated totals")
                if any(x["earned"] > x["maximum"] for x in steps):
                    error("RUBRIC_RANGE", path + ".grade", "Step earned points exceed the step maximum")
            if score < grade["max_points"] and grade["first_divergence"] is None:
                error("MISSING_FIRST_DIVERGENCE", path + ".grade", "A partial score requires the earliest concrete error or missing step")
            if first["raw"].strip().replace(" ", "") in ("1=2", "1＝2") and score == grade["max_points"]:
                error("OBVIOUS_FALSE_FULL_SCORE", path + ".grade", "An explicitly false equality cannot receive full credit")
            if score == grade["max_points"] and item and item.get("release_status") == "FORMATIVE_MACHINE_CHECKED" and item.get("expected"):
                from .mathsafe import check_answer
                try:
                    checked = check_answer(item, first["raw"])
                    if 'REFERENCE_MATH_CONFLICT' in checked.get('error_codes',[]):
                        error('REFERENCE_MATH_CONFLICT',path+'.grade','Stop scoring and independently review the reference')
                    if checked.get("correct") is False or checked.get("result_correct") is False:
                        error("MATH_GRADE_CONTRADICTION", path + ".grade", "Released mathematical constraints contradict the imported full-score claim")
                    elif checked.get("correct") is not True and checked.get("result_correct") is not True:
                        warning("MATH_RESULT_UNSUPPORTED", path + ".grade", "The local checker cannot establish this free-text/photo result; reported grade stays provisional")
                except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
                    warning("MATH_RESULT_UNSUPPORTED", path + ".grade", "No reliable mathematical result check is available: " + type(exc).__name__)
        elif any(x["earned"] is not None for x in steps):
            error("UNSCORED_STEP_CONFLICT", path + ".grade", "Unscored review cannot smuggle numeric step credit")
        divergence = grade["first_divergence"]
        if divergence and divergence["cause"].strip() in ("粗心", "错了", "不认真", "计算错误"):
            error("VAGUE_DIVERGENCE", path + ".grade", "Locate the actual step and explain why its condition or operation fails")
        if attempt["completion"] == "ABANDONED" and not attempt["abandon_reason"]:
            error("ABANDON_REASON", path, "An abandoned attempt needs its actual reason")
        received, feedback = _timestamp(first["received_at"]), _timestamp(attempt["feedback_at"])
        if received and aid not in prior_attempts and received.astimezone(dt.timezone(dt.timedelta(hours=8))).date().isoformat() != card["date"]:
            error("ATTEMPT_RETURN_DATE", path, "A new first answer must belong to the actual training date in Asia/Shanghai")
        if received and feedback and feedback < received:
            error("FEEDBACK_BEFORE_ANSWER", path, "Feedback cannot precede the recorded first answer")
        if attempt["net_seconds"] is not None:
            proof = attempt.get("time_evidence")
            if not proof:
                error("NET_TIME_WITHOUT_EVIDENCE", path, "Unknown per-item time must remain null; no allocation from activity windows")
            else:
                start, end = _timestamp(proof["started_at"]), _timestamp(proof["ended_at"])
                wall = (end - start).total_seconds()
                if wall < 0 or proof["paused_seconds"] > wall or attempt["net_seconds"] > wall - proof["paused_seconds"] + 1e-6:
                    error("INVALID_TIME_INTERVAL", path, "Net time must fit the evidenced wall interval after pauses")
                warning("TIME_NOT_INDEPENDENTLY_VERIFIED", path, "Reported timing does not prove pure thinking time")
        old = prior_attempts.get(aid)
        if old:
            immutable = ("item_id", "item_version", "first_answer", "hint_level", "exposure_declaration", "grade", "feedback_at", "net_seconds", "time_evidence", "completion", "abandon_reason")
            for key in immutable:
                if old.get(key) != attempt.get(key):
                    error("IMMUTABLE_FIRST_ATTEMPT", path + "." + key, "Do not replace an earlier first-answer record; append distinct supplement evidence")
        old_supplements = {x["supplement_id"]: x for x in old.get("supplements", [])} if old else {}
        for n, supplement in enumerate(attempt["supplements"]):
            subpath = path + f".supplements[{n}]"
            sid = supplement["supplement_id"]
            if sid in supplements:
                error("DUPLICATE_SUPPLEMENT", subpath, "Supplement IDs are globally unique")
            supplements.add(sid)
            if sid in old_supplements and old_supplements[sid] != supplement:
                error("IMMUTABLE_SUPPLEMENT", subpath, "An appended evidence page cannot be rewritten")
            assets(supplement["assets"], subpath + ".assets")
            if not supplement["raw"].strip() and not supplement["assets"]:
                error("EMPTY_SUPPLEMENT", subpath, "A supplement must contain actual evidence")
            at = _timestamp(supplement["received_at"])
            if at and received and at < received:
                error("SUPPLEMENT_BEFORE_FIRST", subpath, "A supplement cannot predate receipt of the first answer")
            relation = supplement["relation_to_feedback"]
            if relation != "UNKNOWN" and (at is None or feedback is None):
                error("UNPROVEN_SUPPLEMENT_ORDER", subpath, "Unknown receipt/feedback times cannot be invented to claim before-feedback submission")
            elif at and feedback and relation == "BEFORE_FEEDBACK" and at >= feedback:
                error("SUPPLEMENT_ORDER", subpath, "Post-feedback pages do not become pre-feedback evidence")
            elif at and feedback and relation == "AFTER_FEEDBACK" and at < feedback:
                error("SUPPLEMENT_ORDER", subpath, "Declared ordering conflicts with evidence timestamps")
        if old and not set(old_supplements) <= {x["supplement_id"] for x in attempt["supplements"]}:
            error("SUPPLEMENT_REMOVAL", path, "Prior supplemental evidence must be preserved")

    all_attempts = {**prior_attempts, **attempts}
    event_ids = {event.get("event_id") for row in state.get("repairs", {}).values() if isinstance(row, dict) for event in row.get("actual_answers", []) if isinstance(event, dict)}
    for index, event in enumerate(card["repair_events"]):
        path = f"repair_events[{index}]"
        if event["event_id"] in event_ids:
            error("DUPLICATE_EVENT", path, "Event IDs cannot repeat")
        event_ids.add(event["event_id"])
        if event["origin_attempt_id"] is not None and event["origin_attempt_id"] not in all_attempts:
            error("REPAIR_ORIGIN", path, "Repair origin must reference an actual preserved attempt")
        if event["status"] in ("STARTED", "IN_PROGRESS", "ATTEMPTED", "FORMATIVE_PASSED", "DELAYED_PENDING") and not event["actual_answer"]:
            error("REPAIR_NOT_TRAINED", path, "Generated prompts or plans do not establish a student interaction")
        if event["status"] == "PLANNED" and event["actual_answer"]:
            error("PLANNED_WITH_ANSWER", path, "Record a real interaction using an attempted state")
        if event["item_id"] is not None:
            item = bank_map.get(event["item_id"])
            if not item:
                error("REPAIR_ITEM", path, "Repair item is absent from the known bank")
            if event.get("item_version") is not None and item and event["item_version"] != item.get("item_version", item.get("version_hash")):
                error("REPAIR_ITEM_VERSION", path, "Repair must bind to the exact item version")

    prior_retests = state.get("retests", {})
    prior_events = []
    if isinstance(prior_retests, dict):
        for value in prior_retests.values():
            if isinstance(value, dict) and "stage" in value:
                prior_events.append(value)
            elif isinstance(value, dict):
                prior_events.extend(value.get("events", []))
    elif isinstance(prior_retests, list):
        prior_events = prior_retests
    staged = {}
    used_attempts = {}
    for event in prior_events:
        event_ids.add(event.get("event_id"))
        staged[(event.get("cohort_id"), event.get("stage"))] = event
        used_attempts[event.get("attempt_id")] = (event.get("cohort_id"), event.get("stage"))
    previous_retest_ids = {event.get("event_id") for event in prior_events}
    for index, event in enumerate(card["repair_events"]):
        if event["event_id"] in previous_retest_ids:
            error("DUPLICATE_EVENT", f"repair_events[{index}]", "A previous retest event cannot be replayed as a repair interaction")
    for index, event in enumerate(card["retest_events"]):
        path = f"retest_events[{index}]"
        key = (event["cohort_id"], event["stage"])
        if event["event_id"] in event_ids:
            error("DUPLICATE_EVENT", path, "Event IDs cannot repeat")
        event_ids.add(event["event_id"])
        if key in staged:
            error("DUPLICATE_RETEST_STAGE", path, "A cohort stage cannot be overwritten or counted twice")
        if event["attempt_id"] in used_attempts:
            error("REUSED_RETEST_ATTEMPT", path, "Different retest stages require different preserved first answers")
        attempt = all_attempts.get(event["attempt_id"])
        if not attempt:
            error("RETEST_ATTEMPT", path, "Retest must reference an actual first answer")
        if event["outcome"] == "FORMATIVE_PASS" and attempt:
            grade = attempt["grade"]
            if attempt["hint_level"] or attempt["completion"] != "COMPLETE" or grade["status"] != "FORMATIVE_AI_PROVISIONAL" or grade["score"] != grade["max_points"]:
                error("RETEST_NOT_INDEPENDENT_PASS", path, "Incomplete, hinted, unscored or incorrect work cannot pass a retest")
            if attempt["exposure_declaration"] != "UNSEEN_SELF_DECLARED":
                error("RETEST_EXPOSURE", path, "Seen or uncertain items do not constitute new independent retest evidence")
            current_at = _timestamp(event["at"])
            if current_at is None or attempt["first_answer"]["received_at"] is None:
                error("RETEST_DATE_UNKNOWN", path, "Unknown dates cannot establish delayed stages")
            if current_at:
                local_date = current_at.astimezone(dt.timezone(dt.timedelta(hours=8))).date()
                if local_date.isoformat() != card["date"]:
                    error("RETEST_RETURN_DATE", path, "A delayed event cannot be imported as if it occurred on another training date")
                attempt_at = _timestamp(attempt["first_answer"]["received_at"])
                if attempt_at and (local_date != attempt_at.astimezone(dt.timezone(dt.timedelta(hours=8))).date() or current_at < attempt_at):
                    error("RETEST_ATTEMPT_DATE", path, "A stage date must match its actual first-answer event, not an invented future time")
            previous_stages = {"D0": [], "D3": ["D0"], "D7": ["D0", "D3"], "D14": ["D0", "D3", "D7"]}[event["stage"]]
            for stage in previous_stages:
                previous = staged.get((event["cohort_id"], stage))
                if not previous or previous.get("outcome") != "FORMATIVE_PASS":
                    error("RETEST_STAGE_ORDER", path, "D3/D7/D14 cannot skip or combine cohorts")
                    continue
                previous_at = _timestamp(previous.get("at"))
                if previous_at and current_at and previous_at.date() >= current_at.date():
                    error("RETEST_SAME_DAY", path, "Delayed stages must occur on different actual dates")
                prior_attempt = all_attempts.get(previous.get("attempt_id"))
                if prior_attempt and attempt["item_id"] == prior_attempt["item_id"]:
                    error("RETEST_REUSED_ITEM", path, "Delayed tests must use different unexposed structures")
                if prior_attempt:
                    current_item, prior_item = bank_map.get(attempt["item_id"], {}), bank_map.get(prior_attempt["item_id"], {})
                    if current_item.get("structure_id") and current_item.get("structure_id") == prior_item.get("structure_id"):
                        error("RETEST_REUSED_STRUCTURE", path, "A numeric variant is not a new independent structure")
            d0 = staged.get((event["cohort_id"], "D0"))
            if d0 and current_at and _timestamp(d0.get("at")):
                due = int(event["stage"][1:])
                if (current_at.date() - _timestamp(d0["at"]).date()).days < due:
                    error("RETEST_NOT_DUE", path, "A delayed stage cannot be brought forward to D+1")
        staged[key] = event
        used_attempts[event["attempt_id"]] = key

    if release.get("mode") == "COACH_BUNDLE_LIMITED":
        warning("COACH_BUNDLE_VISIBILITY", "presented_items", "Uploaded coach files are readable; no absolute secrecy or certified unseen status")
    warning("FORMATIVE_ONLY", "declarations", "Validation confirms structure and consistency, not mathematical correctness, human signature, H0 or M4")
    times = card["time_summary"]
    known_times = [v for k, v in times.items() if k != "verified_net_seconds" and v is not None]
    if sum(known_times) > release.get("budget_minutes", 180) * 60:
        warning("BUDGET_EXCEEDED", "time_summary", "Preserve actual overrun; do not invent a compliant elapsed time")
    return {"errors": errors, "warnings": warnings, "normalized": None if errors else normalized}
