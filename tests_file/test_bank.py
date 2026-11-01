"""Public-safe generic tests; real bank payload is read only from local private files.

No actual private question/answer, PILOT mark or unpublished item text is embedded
in this test source. Local bank integration tests skip if it was not supplied.
"""
import copy
import inspect
import json
import shutil
from pathlib import Path

import pytest

from math2_pack import mathsafe as m
from math2_pack.bank import Bank, DEFAULT_PATH, MissingPrivateBank, InvalidPrivateBank, manifest_path, write_manifest


@pytest.fixture(scope="module")
def private_bank():
    if not DEFAULT_PATH.is_file():
        pytest.skip("Private bank intentionally absent from public repository; restore local delivery to run private QA.")
    return Bank()


@pytest.fixture
def local_copy(tmp_path, private_bank):
    target = tmp_path / "private_catalog.json"
    shutil.copyfile(private_bank.path, target)
    shutil.copyfile(manifest_path(private_bank.path), manifest_path(target))
    return target


def test_missing_private_bank_is_actionable_and_does_not_seed(tmp_path):
    path = tmp_path / "missing.json"
    with pytest.raises(MissingPrivateBank, match="公开GitHub"):
        Bank(path)
    assert not path.exists()


def test_invalid_or_duplicate_private_bank_rejected(tmp_path):
    target = tmp_path / "bad.json"
    target.write_text('{"items": [], "items": [], "nodes": []}', encoding="utf-8")
    with pytest.raises(InvalidPrivateBank, match="重复JSON"):
        Bank(target)
    target.write_text('{"not_a_bank": true}', encoding="utf-8")
    with pytest.raises(InvalidPrivateBank, match="items"):
        Bank(target)


def test_mathsafe_is_independent_of_legacy_web_or_database():
    source = inspect.getsource(m)
    for forbidden in ("from app", "import app", "fastapi", "sqlite3", "sqlalchemy", "httpx", "requests"):
        assert forbidden not in source
    assert m.expression("2+2") == 4
    assert m.compare("8/2", {"kind":"expr", "value":"4"})
    assert not m.compare("-4", {"kind":"expr", "value":"4"})


@pytest.mark.parametrize("raw", ["__import__('os').system('whoami')", "open('file')", "x.__class__", "10**100000", "2**(2**12)", "sqrt(-1)", "1/0", "nan", "oo", "(lambda: 2)()"])
def test_generic_bounded_ast_negative_cases(raw):
    with pytest.raises((ValueError, OverflowError)):
        m.expression(raw)


def test_numeric_kernel_generic_positive_negative_and_undeclared_parameters():
    # Synthetic test-only arithmetic, unrelated to the private source bank.
    field={"kind":"span", "value":[[-3],[1]], "matrix":[[1,3]]}
    assert m.compare([[6],[-2]], field)
    assert not m.compare([[0],[0]], field)
    assert not m.compare([[1],[1]], field)
    assert not m.compare([["-3*t"],["t"]], field)
    assert not m.compare([["-3*t/t"],["t/t"]], field)


def test_private_exact_bank_math_and_source_counts(private_bank):
    report=private_bank.validate()
    assert report["status"]=="PASS", report["errors"]
    assert report["original_items"]==293
    assert report["curated_items"]==21
    assert report["nodes"]==67
    assert report["tier2_frozen"]==190
    assert len(report["mathematical_checks"])==21
    assert report["human_reviews"]==report["h0_certified"]==report["certified_r2_items"]==0


def test_seven_family_real_supply_and_shortage_honest(private_bank):
    report=private_bank.validate()
    assert set(report["supply"])=={f"F{i}" for i in range(1,8)}
    for counts in report["supply"].values():
        assert counts["compound_candidates"]==2 and counts["repair_bridges"]==1
        assert counts["certified_r2"]==0
    assert report["seven_day_fresh_supply"]=="INSUFFICIENT_VERIFIED_ITEMS"
    items=private_bank.items()
    assert all(not i["h0_eligible"] for i in items)
    assert all(i["difficulty"]["calibration_status"]=="UNKNOWN" for i in items if i["release_status"]=="FORMATIVE_MACHINE_CHECKED")


def test_nodes_real_names_are_sanitized_from_history(private_bank):
    nodes=private_bank.nodes()
    assert len({n["id"] for n in nodes})==67
    assert all(n["name"]!=n["id"] and n["module"] for n in nodes)
    for node in nodes:
        assert set(node)<={"id","node_id","name","ability_name","module","family","ability_family"}
        assert not any(key in node for key in ("score","mastery_state","historical_claim","historical_item_ids","original_answer_evidence_ref"))


def test_private_fingerprint_and_specialties_are_plans_only(private_bank):
    import hashlib
    assert private_bank.hash==private_bank.fingerprint==hashlib.sha256(private_bank.path.read_bytes()).hexdigest()
    specialties=private_bank.specialties()
    assert {"Q03","Q06"}<=set(specialties)
    for blueprint in specialties.values():
        assert blueprint["status"]=="PLANNED" and blueprint["attempts"]==[] and blueprint["D0"] is None
        assert len(blueprint["steps"])>=3
        assert all(step["status"]=="NOT_STARTED" for step in blueprint["steps"])
        assert any(step.get("item_id") for step in blueprint["steps"])


def test_private_pilot_claims_not_upgraded(private_bank):
    pilot=private_bank.pilot_summary()
    assert pilot["source_kind"]=="FORMATIVE_SECONDARY_REPORT"
    assert pilot["verified_net_seconds"] is None and pilot["per_item_seconds"] is None
    assert pilot["photos"]=="SOURCE_NOT_ATTACHED"
    assert set(pilot["specialties"].values())=={"PROMPT_GENERATED_NOT_TRAINED"}
    assert pilot["verified_h0"]==pilot["verified_m4"]==pilot["instructor_signatures"]==0


@pytest.mark.parametrize("field",["problem","expected","solution","rubric","hints","difficulty","model"])
def test_actual_file_changes_freeze_every_candidate(local_copy,field):
    payload=json.loads(local_copy.read_text(encoding="utf-8"))
    item=next(i for i in payload["items"] if i["release_status"]=="FORMATIVE_MACHINE_CHECKED")
    if field=="problem": item[field]+=" SYNTHETIC_TEST_MUTATION"
    elif field=="expected": item[field][next(iter(item[field]))]["value"]="999"
    elif field=="solution": item[field]["solution_steps"][0]["result"]="SYNTHETIC_TEST_ONLY false derivation"
    elif field=="rubric": item[field][0]["points"]+=1
    elif field=="hints": item[field][0]["text"]="SYNTHETIC_TEST_ONLY modified hint"
    elif field=="difficulty": item[field]["claim"]="R2_CERTIFIED_WITHOUT_EVIDENCE"
    else: item[field]["synthetic_changed_coefficient"]="999"
    local_copy.write_text(json.dumps(payload,ensure_ascii=False),encoding="utf-8")
    bank=Bank(local_copy)
    assert bank.validate()["status"]=="FAIL"
    assert all(i["release_status"].startswith("FROZEN") for i in bank.items())


def test_missing_manifest_is_closed_not_implicitly_published(local_copy):
    manifest_path(local_copy).unlink()
    bank=Bank(local_copy)
    assert bank.validate()["status"]=="FAIL"
    assert all(i["release_status"].startswith("FROZEN") for i in bank.items())


def test_borrowed_objects_cannot_mutate_the_bank(private_bank):
    item=next(i for i in private_bank.items() if i["release_status"]=="FORMATIVE_MACHINE_CHECKED")
    original=item["problem"]
    item["problem"]="SYNTHETIC_TEST_ONLY modified return object"
    assert private_bank.get(item["id"])["problem"]==original
    nodes=private_bank.nodes();nodes[0]["name"]="changed"
    assert private_bank.nodes()[0]["name"]!="changed"


def test_all_local_answers_are_only_provisional_and_free_process_pending(private_bank):
    for item in private_bank.items():
        if item["release_status"]!="FORMATIVE_MACHINE_CHECKED": continue
        result={k:v["value"] for k,v in item["expected"].items()}
        grade=m.check_answer(item,json.dumps(result))
        assert grade["correct"] is True
        assert grade["certificate"]=="FORMATIVE_AI_PROVISIONAL"
        assert grade["h0_status"]=="PROVISIONAL_NOT_CERTIFIED"
        grade=m.check_answer(item,json.dumps({"answers":result,"work_text":"SYNTHETIC_TEST_ONLY unverified narrative"}))
        assert grade["score"] is None and grade["correct"] is None
        assert grade["grade_status"]=="PENDING_HUMAN_REVIEW" and not grade["process_verified"]


def test_rehashing_an_incorrect_answer_does_not_replace_mathematical_qa(local_copy):
    payload=json.loads(local_copy.read_text(encoding="utf-8"))
    item=next(i for i in payload["items"] if i["release_status"]=="FORMATIVE_MACHINE_CHECKED")
    item["expected"][next(iter(item["expected"]))]["value"]="999"
    item["version_hash"]=m.item_digest(item)
    local_copy.write_text(json.dumps(payload,ensure_ascii=False),encoding="utf-8")
    write_manifest(local_copy)
    report=Bank(local_copy).validate()
    assert report["status"]=="FAIL"
    assert any("MATH_QA:" in error for error in report["errors"])
    assert all(i["release_status"].startswith("FROZEN") for i in Bank(local_copy).items())
