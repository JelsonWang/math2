"""Public tests use only invented IDs and synthetic evidence, never learner data."""
from __future__ import annotations

import copy
import json
import math

import pytest

from math2_pack.returns import validate_return, load_schema


HASH = "a" * 64
VERSION = "b" * 64


def fixture():
    bank = {f"SYN-ITEM-{n}": {"id": f"SYN-ITEM-{n}", "version_hash": VERSION, "max_points": 10, "release_status": "FORMATIVE_MACHINE_CHECKED", "initial_exposure": "NEW_GENERATED_UNSEEN", "structure_id": f"SYN-STRUCTURE-{n}"} for n in range(5)}
    release = {"version": "1.0", "release_id": "SYN-RELEASE-001", "date": "2026-01-01", "record_kind": "SYNTHETIC_TEST_ONLY", "source_state_hash": HASH, "mode": "ACTIVE_ITEM_STRICT", "budget_minutes": 170,
               "item_refs": [{"item_id": key, "item_version": VERSION, "max_points": 10, "role": "MAINLINE", "exposure_eligibility": "UNSEEN_SELF_DECLARED"} for key in bank]}
    state = {"record_kind": "SYNTHETIC_TEST_ONLY", "source_state_hash": HASH, "attempts": {}, "exposures": {}, "repairs": {}, "retests": {}}
    card = {"version": "1.0", "record_kind": "SYNTHETIC_TEST_ONLY", "release_id": release["release_id"], "date": release["date"], "source_state_hash": HASH,
            "presented_items": [], "attempts": [], "repair_events": [], "retest_events": [],
            "time_summary": {"activity_window_seconds": None, "verified_net_seconds": None, "feedback_seconds": None, "specialty_seconds": None, "review_seconds": None},
            "review": {"summary": "SYNTHETIC_TEST_ONLY: a structural test, no real score or teacher approval", "unresolved": [], "next_actions": ["Continue an actual exercise"]},
            "declarations": {"teacher_signatures": False, "official_exam_score": None, "certified_h0": False, "certified_m4": False}}
    return card, release, bank, state


def add_attempt(card, index=0, at=None, score=10):
    iid = f"SYN-ITEM-{index}"
    attempt = {"attempt_id": f"SYN-ATTEMPT-{index}", "item_id": iid, "item_version": VERSION,
               "first_answer": {"raw": "SYNTHETIC_TEST_ONLY independent written response", "assets": [], "received_at": at}, "hint_level": 0,
               "exposure_declaration": "UNSEEN_SELF_DECLARED", "grade": {"status": "FORMATIVE_AI_PROVISIONAL", "score": score, "max_points": 10,
               "confidence": "LOW", "first_divergence": None if score == 10 else {"location": "line 2", "student": "a missing boundary term", "correction": "retain the boundary term", "cause": "The endpoint term was omitted before substitution."},
               "step_scores": [{"step_id": "SYN-STEP", "earned": score, "maximum": 10, "reason": "SYNTHETIC_TEST_ONLY provisional per-step reasoning"}]},
               "feedback_at": at, "net_seconds": None, "completion": "COMPLETE", "abandon_reason": None, "supplements": []}
    card["attempts"].append(attempt)
    card["presented_items"].append({"item_id": iid, "item_version": VERSION, "presented_at": at, "exposure": "CONFIRMED_SEEN"})
    return attempt


def validate(parts):
    return validate_return(*parts)


def codes(result):
    return {x["code"] for x in result["errors"]}


def test_schema_is_strict_and_nullable_unknown_evidence_is_preserved():
    parts = fixture()
    attempt = add_attempt(parts[0])
    original = copy.deepcopy(parts)
    report = validate(parts)
    assert report["errors"] == []
    assert report["normalized"]["attempts"][0]["net_seconds"] is None
    assert report["normalized"]["attempts"][0]["first_answer"]["received_at"] is None
    assert report["normalized"]["declarations"]["certified_h0"] is False
    assert parts == original  # the validator has no caller mutation side effects
    assert report["normalized"] is not parts[0]
    assert "FORMATIVE_ONLY" in {x["code"] for x in report["warnings"]}
    assert load_schema()["additionalProperties"] is False


@pytest.mark.parametrize("field,value", [("teacher_signatures", True), ("certified_h0", True), ("certified_m4", True), ("official_exam_score", 150)])
def test_no_forged_teacher_h0_m4_or_formal_exam_certificate(field, value):
    parts = fixture()
    parts[0]["declarations"][field] = value
    result = validate(parts)
    assert "SCHEMA" in codes(result)
    assert result["normalized"] is None


@pytest.mark.parametrize("mutation", ["unknown-field", "wrong-version", "wrong-hash", "unknown-item", "wrong-item-version", "future-field-trust", "bad-date", "no-zone"])
def test_schema_and_release_exact_references_reject_corruption(mutation):
    parts = fixture()
    attempt = add_attempt(parts[0])
    if mutation == "unknown-field": parts[0]["is_pass"] = True
    if mutation == "wrong-version": parts[0]["version"] = "999"
    if mutation == "wrong-hash": parts[0]["source_state_hash"] = "c" * 64
    if mutation == "unknown-item": attempt["item_id"] = "SYN-MISSING-ITEM"
    if mutation == "wrong-item-version": attempt["item_version"] = "d" * 64
    if mutation == "future-field-trust": attempt["grade"]["teacher_verified"] = True
    if mutation == "bad-date": parts[0]["date"] = "2026-02-31"
    if mutation == "no-zone": attempt["first_answer"]["received_at"] = "2026-01-01T09:00:00"
    assert validate(parts)["errors"]


@pytest.mark.parametrize("location", ["release", "state", "card"])
def test_synthetic_real_history_isolation(location):
    parts = fixture()
    add_attempt(parts[0])
    target = {"card": 0, "release": 1, "state": 3}[location]
    parts[target]["record_kind"] = "REAL"
    assert validate(parts)["errors"]


def test_missing_presentation_duplicate_ids_and_false_unseen_are_rejected():
    parts = fixture()
    attempt = add_attempt(parts[0])
    parts[0]["presented_items"] = []
    assert "ATTEMPT_WITHOUT_PRESENTATION" in codes(validate(parts))
    parts = fixture()
    add_attempt(parts[0])
    parts[0]["attempts"].append(copy.deepcopy(parts[0]["attempts"][0]))
    assert "DUPLICATE_ATTEMPT" in codes(validate(parts))
    parts = fixture()
    add_attempt(parts[0])
    parts[3]["exposures"]["SYN-ITEM-0"] = {"state": "CONFIRMED_SEEN"}
    assert "EXPOSURE_DOWNGRADE" in codes(validate(parts))
    parts[3]["exposures"]["SYN-ITEM-0"]["state"] = "UNKNOWN_POSSIBLY_EXPOSED"
    assert "EXPOSURE_DOWNGRADE" in codes(validate(parts))
    parts[0]["attempts"][0]["exposure_declaration"] = "CONFIRMED_SEEN"
    assert validate(parts)["errors"] == []


def test_readable_coach_bundle_can_record_unknown_visibility_but_not_unseen_claim():
    parts = fixture()
    parts[1]["mode"] = "COACH_BUNDLE_LIMITED"
    add_attempt(parts[0])
    assert "BUNDLE_NOT_UNSEEN" in codes(validate(parts))
    parts[0]["attempts"][0]["exposure_declaration"] = "UNKNOWN_POSSIBLY_EXPOSED"
    parts[0]["presented_items"].append({"item_id": "SYN-ITEM-1", "item_version": VERSION, "presented_at": None, "exposure": "UNKNOWN_POSSIBLY_EXPOSED"})
    result = validate(parts)
    assert result["errors"] == []
    assert result["normalized"]["presented_items"][1]["exposure"] == "UNKNOWN_POSSIBLY_EXPOSED"
    assert "COACH_BUNDLE_VISIBILITY" in {x["code"] for x in result["warnings"]}


@pytest.mark.parametrize("mutation,expected", [("missing-steps", "SCORE_WITHOUT_STEPS"), ("wrong-total", "RUBRIC_TOTAL"), ("over-max", "SCORE_RANGE"), ("wrong-step-range", "RUBRIC_RANGE"), ("pending-score", "PENDING_NOT_SCORED"), ("unsupported-certificate", "SCHEMA"), ("false-equality-full", "OBVIOUS_FALSE_FULL_SCORE"), ("partial-no-location", "MISSING_FIRST_DIVERGENCE")])
def test_empty_or_conflicting_grading_claims_do_not_validate(mutation, expected):
    parts = fixture()
    attempt = add_attempt(parts[0])
    grade = attempt["grade"]
    if mutation == "missing-steps": grade["step_scores"] = []
    if mutation == "wrong-total": grade["step_scores"][0]["earned"] = 4
    if mutation == "over-max": grade["score"] = 11
    if mutation == "wrong-step-range": grade["step_scores"][0]["maximum"] = 9
    if mutation == "pending-score": grade["status"] = "PENDING_HUMAN_REVIEW"
    if mutation == "unsupported-certificate": grade["status"] = "INSTRUCTOR_VERIFIED_H0"
    if mutation == "false-equality-full": attempt["first_answer"]["raw"] = "1=2"
    if mutation == "partial-no-location": grade["score"] = grade["step_scores"][0]["earned"] = 4
    assert expected in codes(validate(parts))


def test_pending_photo_or_free_text_can_remain_unscored_without_fake_ocr():
    parts = fixture()
    attempt = add_attempt(parts[0])
    attempt["first_answer"]["raw"] = "SOURCE_NOT_ATTACHED: image was visible in chat; original bytes were not exported."
    attempt["grade"].update(status="PENDING_HUMAN_REVIEW", score=None, step_scores=[], first_divergence=None, confidence="UNKNOWN")
    result = validate(parts)
    assert result["errors"] == []
    assert result["normalized"]["attempts"][0]["first_answer"]["assets"] == []
    assert result["normalized"]["attempts"][0]["grade"]["score"] is None


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), True, 999999999])
def test_invalid_elapsed_values_are_rejected(value):
    parts = fixture()
    add_attempt(parts[0])["net_seconds"] = value
    assert validate(parts)["errors"]


def test_no_fabricated_net_time_and_valid_manual_timing_remains_unverified():
    parts = fixture()
    attempt = add_attempt(parts[0])
    attempt["net_seconds"] = 30
    assert "NET_TIME_WITHOUT_EVIDENCE" in codes(validate(parts))
    attempt["time_evidence"] = {"kind": "USER_REPORTED", "started_at": "2026-01-01T09:00:00Z", "ended_at": "2026-01-01T09:01:00Z", "paused_seconds": 10, "source_ref": "SYNTHETIC_TEST_ONLY manual timer"}
    result = validate(parts)
    assert result["errors"] == []
    assert result["normalized"]["time_summary"]["verified_net_seconds"] is None
    attempt["net_seconds"] = 51
    assert "INVALID_TIME_INTERVAL" in codes(validate(parts))
    attempt["net_seconds"] = None
    parts[0]["time_summary"]["verified_net_seconds"] = 50
    assert "SCHEMA" in codes(validate(parts))


def test_first_answer_and_supplements_are_immutable_but_append_is_supported():
    parts = fixture()
    attempt = add_attempt(parts[0], at="2026-01-01T09:00:00Z")
    attempt["feedback_at"] = "2026-01-01T09:10:00Z"
    parts[3]["attempts"][attempt["attempt_id"]] = copy.deepcopy(attempt)
    parts[3]["exposures"][attempt["item_id"]] = {"state": "CONFIRMED_SEEN", "source": "PRIOR_SYNTHETIC_PRESENTATION"}
    attempt["first_answer"]["raw"] = "Rewritten original"
    assert "IMMUTABLE_FIRST_ATTEMPT" in codes(validate(parts))
    attempt["first_answer"]["raw"] = parts[3]["attempts"][attempt["attempt_id"]]["first_answer"]["raw"]
    supplement = {"supplement_id": "SYN-SUPPLEMENT-1", "raw": "Actual later page", "assets": [], "received_at": "2026-01-01T09:11:00Z", "relation_to_feedback": "AFTER_FEEDBACK"}
    attempt["supplements"].append(supplement)
    assert validate(parts)["errors"] == []
    supplement["relation_to_feedback"] = "BEFORE_FEEDBACK"
    assert "SUPPLEMENT_ORDER" in codes(validate(parts))
    supplement["relation_to_feedback"] = "AFTER_FEEDBACK"
    parts[3]["attempts"][attempt["attempt_id"]] = copy.deepcopy(attempt)
    supplement["raw"] = "Overwrite a sealed supplement"
    assert "IMMUTABLE_SUPPLEMENT" in codes(validate(parts))
    attempt["supplements"] = []
    assert "SUPPLEMENT_REMOVAL" in codes(validate(parts))


def test_unknown_supplement_order_stays_unknown_and_unsafe_asset_paths_fail():
    parts = fixture()
    attempt = add_attempt(parts[0])
    attempt["supplements"] = [{"supplement_id": "SYN-SUPPLEMENT", "raw": "Actual page; original writing time unknown", "assets": [], "received_at": None, "relation_to_feedback": "UNKNOWN"}]
    assert validate(parts)["errors"] == []
    attempt["supplements"][0]["relation_to_feedback"] = "BEFORE_FEEDBACK"
    assert "UNPROVEN_SUPPLEMENT_ORDER" in codes(validate(parts))
    attempt["supplements"] = []
    for name in ("../page.png", "C:/private/page.png", "/root/page.png", "\\\\server\\page.png", "bad\x00.png"):
        attempt["first_answer"]["assets"] = [{"path": name, "sha256": "c" * 64}]
        assert "UNSAFE_ASSET_PATH" in codes(validate(parts))


def test_prompt_generated_does_not_become_actual_specialty_training():
    parts = fixture()
    attempt = add_attempt(parts[0], score=4)
    event = {"event_id": "SYN-REPAIR-E1", "repair_id": "SYN-REPAIR-1", "origin_attempt_id": attempt["attempt_id"], "status": "PLANNED", "actual_answer": None, "item_id": None, "at": None}
    parts[0]["repair_events"] = [event]
    assert validate(parts)["errors"] == []
    event["status"] = "STARTED"
    assert "REPAIR_NOT_TRAINED" in codes(validate(parts))
    event["status"] = "FORMATIVE_PASSED"
    assert "REPAIR_NOT_TRAINED" in codes(validate(parts))
    event.update(status="ATTEMPTED", actual_answer="SYNTHETIC_ONLY actual learner interaction")
    assert validate(parts)["errors"] == []
    event["origin_attempt_id"] = "SYN-NONEXISTENT"
    assert "REPAIR_ORIGIN" in codes(validate(parts))


def delayed_fixture():
    state = fixture()[3]
    for index, day in enumerate((1, 4, 8, 15)):
        card, release, bank, _ = fixture()
        card["date"] = release["date"] = f"2026-01-{day:02d}"
        attempt = add_attempt(card, index, f"2026-01-{day:02d}T09:00:00Z")
        card["retest_events"].append({"event_id": f"SYN-RETEST-{index}", "cohort_id": "SYN-COHORT", "stage": ("D0", "D3", "D7", "D14")[index], "attempt_id": attempt["attempt_id"], "outcome": "FORMATIVE_PASS", "at": attempt["first_answer"]["received_at"]})
        parts = (card, release, bank, copy.deepcopy(state))
        assert validate(parts)["errors"] == []
        state["attempts"][attempt["attempt_id"]] = copy.deepcopy(attempt)
        state["retests"].setdefault("SYN-COHORT", {"events": []})["events"].append(copy.deepcopy(card["retest_events"][0]))
    return parts


def test_delayed_formative_stages_never_certify_real_h0_or_m4():
    parts = delayed_fixture()
    result = validate(parts)
    assert result["errors"] == []
    assert not result["normalized"]["declarations"]["certified_m4"]
    assert not result["normalized"]["declarations"]["certified_h0"]


@pytest.mark.parametrize("mutation,expected", [("skip", "RETEST_STAGE_ORDER"), ("same-day", "RETEST_SAME_DAY"), ("early", "RETEST_NOT_DUE"), ("reuse", "REUSED_RETEST_ATTEMPT"), ("cross-cohort", "RETEST_STAGE_ORDER"), ("hinted", "RETEST_NOT_INDEPENDENT_PASS"), ("unknown-exposure", "RETEST_EXPOSURE"), ("unknown-date", "RETEST_DATE_UNKNOWN"), ("same-structure", "RETEST_REUSED_STRUCTURE")])
def test_delayed_retest_counterexamples(mutation, expected):
    parts = delayed_fixture()
    events = parts[0]["retest_events"]
    if mutation == "skip": parts[3]["retests"] = {}
    if mutation == "same-day": parts[3]["retests"]["SYN-COHORT"]["events"][2]["at"] = events[0]["at"]
    if mutation == "early":
        parts[0]["date"] = parts[1]["date"] = "2026-01-02"
        events[0]["at"] = parts[0]["attempts"][0]["first_answer"]["received_at"] = "2026-01-02T09:00:00Z"
    if mutation == "reuse": events[0]["attempt_id"] = "SYN-ATTEMPT-2"
    if mutation == "cross-cohort": events[0]["cohort_id"] = "SYN-OTHER-COHORT"
    if mutation == "hinted": parts[0]["attempts"][0]["hint_level"] = 1
    if mutation == "unknown-exposure": parts[0]["attempts"][0]["exposure_declaration"] = "UNKNOWN_POSSIBLY_EXPOSED"
    if mutation == "unknown-date": events[0]["at"] = None
    if mutation == "same-structure": parts[2]["SYN-ITEM-3"]["structure_id"] = parts[2]["SYN-ITEM-0"]["structure_id"]
    assert expected in codes(validate(parts))


def test_frozen_content_or_maximum_changes_do_not_validate():
    parts = fixture()
    add_attempt(parts[0])
    parts[2]["SYN-ITEM-0"]["release_status"] = "FROZEN_REVIEW_PENDING"
    assert "FROZEN_ITEM" in codes(validate(parts))
    parts[2]["SYN-ITEM-0"]["release_status"] = "FORMATIVE_MACHINE_CHECKED"
    parts[0]["attempts"][0]["grade"]["max_points"] = 11
    assert "MAX_POINTS" in codes(validate(parts))


def test_supported_list_bank_shape_and_preserved_true_overtime_warning():
    parts = list(fixture())
    add_attempt(parts[0])
    parts[2] = list(parts[2].values())
    parts[0]["time_summary"]["activity_window_seconds"] = 12000
    result = validate(parts)
    assert result["errors"] == []
    assert "BUDGET_EXCEEDED" in {x["code"] for x in result["warnings"]}
    assert result["normalized"]["time_summary"]["activity_window_seconds"] == 12000


def test_empty_template_is_not_training_evidence():
    result = validate(fixture())
    assert "EMPTY_RETURN_NOT_LEARNING_EVIDENCE" in codes(result)
    assert result["normalized"] is None


def test_optional_error_codes_and_dimension_observations_are_provisional():
    parts = fixture()
    attempt = add_attempt(parts[0], score=4)
    attempt["grade"]["error_codes"] = ["R6", "R7"]
    attempt["grade"]["dimensions"] = {"R": None, "C": "FORMATIVE_BREAKPOINT", "F": "Original final value was incomplete"}
    result = validate(parts)
    assert result["errors"] == []
    assert result["normalized"]["attempts"][0]["grade"]["dimensions"]["R"] is None
    attempt["grade"]["dimensions"]["F"] = "DELAYED_VERIFIED_M4"
    assert "DIMENSION_CERTIFICATE" in codes(validate(parts))
    attempt["grade"]["dimensions"] = {}
    attempt["grade"]["error_codes"] = ["ALL_CERTIFIED_PASS"]
    assert "SCHEMA" in codes(validate(parts))


def test_another_id_cannot_create_another_first_answer_to_same_item():
    parts = fixture()
    attempt = add_attempt(parts[0])
    duplicate = copy.deepcopy(attempt)
    duplicate["attempt_id"] = "SYN-DUPLICATE-NEW-ID"
    parts[0]["attempts"].append(duplicate)
    assert "DUPLICATE_FIRST_ITEM" in codes(validate(parts))
    parts[0]["attempts"].pop()
    parts[3]["attempts"]["SYN-AN-EARLIER-ID"] = copy.deepcopy(attempt)
    assert "EXPOSURE_DOWNGRADE" in codes(validate(parts))


def test_new_attempt_date_cannot_be_rewritten_to_fake_training_day():
    parts = fixture()
    add_attempt(parts[0], at="2026-01-02T09:00:00Z")
    assert "ATTEMPT_RETURN_DATE" in codes(validate(parts))
    parts = delayed_fixture()
    parts[0]["retest_events"][0]["at"] = "2026-01-16T09:00:00Z"
    assert "RETEST_ATTEMPT_DATE" in codes(validate(parts))
    assert "RETEST_RETURN_DATE" in codes(validate(parts))


def test_retroactive_daily_updates_and_windows_path_aliases_fail_closed():
    parts = fixture()
    attempt = add_attempt(parts[0])
    parts[3]["last_training_date"] = "2026-01-02"
    assert "RETROACTIVE_DAILY_RETURN" in codes(validate(parts))
    parts[3]["last_training_date"] = None
    for path in ("assets/NUL", "assets/CON.png", "assets/page.png.", "assets/.. /page.png"):
        attempt["first_answer"]["assets"] = [{"path": path, "sha256": "c" * 64}]
        assert "UNSAFE_ASSET_PATH" in codes(validate(parts))
    attempt["first_answer"]["assets"] = [{"path": "assets/page.png", "sha256": "c" * 64}, {"path": "assets\\page.png", "sha256": "d" * 64}]
    assert "ASSET_HASH_CONFLICT" in codes(validate(parts))


def mathematical_fixture(fields=None):
    from math2_pack.mathsafe import item_digest
    parts = fixture()
    item = parts[2]["SYN-ITEM-0"]
    item["expected"] = fields or {"value": {"kind": "expr", "value": "4", "dimension": "C"}}
    item['model']={'type':'symbolic_tasks','tasks':{k:{'op':'limit','expr':v['value']+'+x','at':'0'} for k,v in item['expected'].items()}}
    item['solution']={'solution_steps':[{'result':'synthetic define'},{'result':'synthetic evaluate'},{'result':'synthetic conclude'}]}
    item['rubric']=[{'field':k,'points':item['max_points']/len(item['expected'])} for k in item['expected']]
    item["version_hash"] = item_digest(item)
    parts[1]["item_refs"][0]["item_version"] = item["version_hash"]
    attempt = add_attempt(parts[0])
    attempt["item_version"] = parts[0]["presented_items"][0]["item_version"] = item["version_hash"]
    return parts, attempt


def test_supported_math_cannot_import_a_false_full_score_but_equivalent_result_is_formative():
    parts, attempt = mathematical_fixture()
    attempt["first_answer"]["raw"] = json.dumps({"value": "-4"})
    result = validate(parts)
    assert "MATH_GRADE_CONTRADICTION" in codes(result)
    assert result["normalized"] is None
    attempt["first_answer"]["raw"] = json.dumps({"value": "2+2"})
    positive = validate(parts)
    assert positive["errors"] == []
    assert positive["normalized"]["declarations"]["certified_h0"] is False
    assert positive["normalized"]["attempts"][0]["grade"]["status"] == "FORMATIVE_AI_PROVISIONAL"


def test_unsupported_free_text_is_flagged_without_inventing_a_math_pass():
    fields = {"first": {"kind": "expr", "value": "4", "dimension": "C"}, "second": {"kind": "expr", "value": "5", "dimension": "F"}}
    parts, attempt = mathematical_fixture(fields)
    attempt["first_answer"]["raw"] = "SYNTHETIC_ONLY: a free-text argument the local tool cannot parse"
    result = validate(parts)
    assert result["errors"] == []
    assert "MATH_RESULT_UNSUPPORTED" in {x["code"] for x in result["warnings"]}
    attempt["first_answer"]["raw"] = "1=2"
    assert "OBVIOUS_FALSE_FULL_SCORE" in codes(validate(parts))
