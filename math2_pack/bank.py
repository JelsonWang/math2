"""Private, version-bound bank for the ChatGPT file workflow.

The public repository deliberately contains no learner history or usable question
payload. A local private bank and its manifest are required to build real packs.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from .mathsafe import digest, item_digest, validate_math
from .quality import mapping_errors, calibration


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "verified_bank" / "private_catalog.json"
SCHEMA_VERSION = "math2.private-bank.v1"
FAMILIES = tuple(f"F{i}" for i in range(1, 8))
SOURCE_COUNTS = {
    "items": 293, "student_items": 293, "teacher_solutions": 293,
    "rubrics": 293, "hint_levels": 293, "exposure_registry": 293,
    "mastery_state": 67, "attempt_events": 0, "retest_schedule": 0,
    "coverage_plan": 7,
}


class MissingPrivateBank(FileNotFoundError):
    """No private content was found; never replace it with invented real data."""


class InvalidPrivateBank(ValueError):
    pass


def manifest_path(path: Path) -> Path:
    return path.with_suffix(".manifest.json")


def _strict_json(text):
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise InvalidPrivateBank("重复JSON字段：" + key)
            out[key] = value
        return out
    return json.loads(text, object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(InvalidPrivateBank("非有限JSON常量：" + value)))


class Bank:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path).expanduser().resolve() if path is not None else DEFAULT_PATH
        self._validation_cache = {}
        if not self.path.is_file():
            raise MissingPrivateBank(
                f"缺少本地私有题库：{self.path}。请从本次本地交付或你自己的受控备份恢复 "
                "private_catalog.json 及 private_catalog.manifest.json；不要上传到公开GitHub。"
                "也可用命令的 --bank 参数指定已有私有题库。公共代码不会自动制造题目、历史或认证。"
            )
        self._read()

    def _read(self):
        try:
            raw = self.path.read_bytes()
            data = _strict_json(raw.decode("utf-8-sig"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise InvalidPrivateBank("私有题库不是合法UTF-8 JSON：" + str(exc)) from exc
        if not isinstance(data, dict) or not isinstance(data.get("items"), list) or not isinstance(data.get("nodes"), list):
            raise InvalidPrivateBank("私有题库必须包含items和nodes数组；禁止空目录假装已导入。")
        if any(not isinstance(item, dict) or not isinstance(item.get("id"), str) or not isinstance(item.get("nodes", []), list) or not isinstance(item.get("families", []), list) for item in data["items"]):
            raise InvalidPrivateBank("题目记录必须包含字符串id及nodes/families数组。")
        if any(not isinstance(node, dict) for node in data["nodes"]) or not isinstance(data.get("pilot", {}), dict) or not isinstance(data.get("sources", {}), dict):
            raise InvalidPrivateBank("节点、PILOT摘要或来源对象结构不合法。")
        return data, raw

    def _integrity(self, data, raw):
        errors = []
        path = manifest_path(self.path)
        if not path.is_file():
            return ["MISSING_PRIVATE_MANIFEST：请从受控备份同时恢复 " + str(path)]
        try:
            manifest = _strict_json(path.read_text(encoding="utf-8-sig"))
            if manifest.get("bank_sha256") != hashlib.sha256(raw).hexdigest():
                errors.append("PRIVATE_BANK_SHA256_MISMATCH：当前实际文件与发布清单不一致。")
            versions = manifest.get("item_payload_sha256", {})
            if set(versions) != {item.get("id") for item in data["items"]}:
                errors.append("ITEM_MANIFEST_REFERENCE_MISMATCH")
            for item in data["items"]:
                if versions.get(item.get("id")) != digest(item):
                    errors.append("ITEM_PAYLOAD_CHANGED:" + str(item.get("id")))
            if manifest.get("nodes_sha256") != digest(data["nodes"]):
                errors.append("NODE_METADATA_CHANGED")
            if manifest.get("pilot_sha256") != digest(data.get("pilot")):
                errors.append("PILOT_SUMMARY_CHANGED")
            if manifest.get("sources_sha256") != digest(data.get("sources")):
                errors.append("SOURCE_PROVENANCE_CHANGED")
            if manifest.get("specialties_sha256") != digest(data.get("specialties")):
                errors.append("SPECIALTY_BLUEPRINT_CHANGED")
        except (OSError, UnicodeError, ValueError, TypeError, AttributeError) as exc:
            errors.append("INVALID_PRIVATE_MANIFEST:" + str(exc))
        return errors

    def items(self):
        """Return private records; any changed payload is frozen before selection."""
        data, raw = self._read()
        report = self.validate()
        integrity = list(report["errors"])
        if report.get("bank_sha256") != hashlib.sha256(raw).hexdigest():
            integrity.append("PRIVATE_BANK_CHANGED_DURING_READ")
        items = copy.deepcopy(data["items"])
        for item in items:
            if integrity and not str(item.get("release_status", "")).startswith("FROZEN"):
                item["published_version_hash"] = item.get("version_hash")
                item["release_status"] = "FROZEN_PRIVATE_BANK_INTEGRITY_FAILURE"
                item["release_reason"] = "; ".join(integrity)
                item["version_hash"] = item_digest(item)
            elif item.get("release_status") == "FORMATIVE_MACHINE_CHECKED" and item_digest(item) != item.get("version_hash"):
                item["published_version_hash"] = item.get("version_hash")
                item["release_status"] = "FROZEN_CONTENT_VERSION_MISMATCH"
                item["release_reason"] = "题面、推导、答案、评分或提示与核验版本不同。"
                item["version_hash"] = item_digest(item)
        return items

    def get(self, iid):
        for item in self.items():
            if item["id"] == iid:
                return item
        raise KeyError("题库不存在此稳定ID：" + str(iid))

    @property
    def hash(self):
        """SHA256 of actual current private bank bytes, not a self-reported field."""
        _, raw = self._read()
        return hashlib.sha256(raw).hexdigest()

    @property
    def fingerprint(self):
        return self.hash

    def nodes(self):
        # A public node projection never carries old marks, evidence pointers,
        # presumed mastery, prompt exposure, or original handwriting claims.
        data, _ = self._read()
        allowed = ("id", "node_id", "name", "ability_name", "module", "family", "ability_family")
        return [{k: copy.deepcopy(node[k]) for k in allowed if k in node} for node in data["nodes"]]

    def pilot_summary(self):
        """Private local history only. Never include this in public repository assets."""
        data, _ = self._read()
        return copy.deepcopy(data.get("pilot", {}))

    def specialties(self):
        report = self.validate()
        if report["status"] != "PASS":
            raise InvalidPrivateBank("专项来源版本未通过校验：" + "; ".join(report["errors"]))
        data, _ = self._read()
        return copy.deepcopy(data.get("specialties", {}))

    def validate(self):
        """Read actual current bytes and independently recompute all curated models."""
        data, raw = self._read()
        bank_sha256 = hashlib.sha256(raw).hexdigest()
        manifest = manifest_path(self.path)
        manifest_sha256 = hashlib.sha256(manifest.read_bytes()).hexdigest() if manifest.is_file() else None
        cache_key = (bank_sha256, manifest_sha256)
        if cache_key in self._validation_cache:
            return copy.deepcopy(self._validation_cache[cache_key])
        errors = self._integrity(data, raw)
        integrity_failed = bool(errors)
        checks = []
        items = data["items"]
        original = [i for i in items if i.get("source") == "GEMINI_V25_CANDIDATE"]
        curated = [i for i in items if i.get("source") == "NEW_LOCAL_FORMATIVE_20261101"]
        if data.get("schema_version") != SCHEMA_VERSION:
            errors.append("UNSUPPORTED_PRIVATE_BANK_SCHEMA")
        ids = [i.get("id") for i in items]
        if len(ids) != len(set(ids)):
            errors.append("DUPLICATE_ITEM_ID")
        nodes = self.nodes()
        node_ids = [n.get("id", n.get("node_id")) for n in nodes]
        if len(nodes) != 67 or len(set(node_ids)) != 67 or any(not n.get("name") or not n.get("module") for n in nodes):
            errors.append("NODE_METADATA_67_REQUIRED")
        extensions=[i for i in items if i.get('source')=='LOCAL_REVIEWED_EXTENSION']
        if len(original) != 293 or len(curated) != 21 or len(items) != 314+len(extensions):
            errors.append(f"ITEM_DENOMINATOR_MISMATCH: originals={len(original)}, curated={len(curated)}, total={len(items)}")
        if sum(i.get("tier") == "TIER2" for i in original) != 190:
            errors.append("TIER2_DENOMINATOR_MUST_BE_190")
        for item in original:
            if not str(item.get("release_status", "")).startswith("FROZEN") or item.get("h0_eligible") is not False:
                errors.append("UNREVIEWED_SOURCE_RELEASED:" + item["id"])
        for item in items:
            if not set(item.get("nodes", [])) <= set(node_ids):
                errors.append("UNKNOWN_NODE_REFERENCE:" + item["id"])
        for item in curated+extensions:
            if integrity_failed:
                # Already frozen: do not treat computations on a changed,
                # unpublished payload as mathematical release evidence.
                continue
            try:
                if item_digest(item) != item.get("version_hash"):
                    raise AssertionError("当前载荷hash与声明版本不一致")
                if item.get("release_status") != "FORMATIVE_MACHINE_CHECKED" or item.get("h0_eligible") is not False or item.get("teacher_review") != "NOT_PERFORMED":
                    raise AssertionError("新题只能形成性发布，不能伪造审核或H0")
                if item.get("difficulty", {}).get("calibration_status") != "UNKNOWN":
                    raise AssertionError("没有真实校准记录，不能更改难度校准状态")
                if not item.get("structure_id"):
                    raise AssertionError("必须保留结构标识；换数字不是新结构")
                checks.append(validate_math(item))
                if item in extensions:
                    if not item.get('node_fields') or not item.get('training_roles'):
                        raise AssertionError('新题需子问映射与训练用途')
                    issues=mapping_errors(item)
                    if issues:raise AssertionError(';'.join(issues))
            except Exception as exc:
                errors.append("MATH_QA:" + item.get("id", "?") + ":" + str(exc))
        sources = data.get("sources", {})
        tables = sources.get("tables", {})
        table_counts = {name: len(value) for name, value in tables.items() if isinstance(value, list)}
        if table_counts != SOURCE_COUNTS:
            errors.append("TEN_SOURCE_TABLE_COUNTS_MISMATCH")
        if any(digest(tables.get(name)) != sources.get("table_payload_sha256", {}).get(name) for name in SOURCE_COUNTS):
            errors.append("SOURCE_TABLE_PAYLOAD_CHANGED")
        pilot = data.get("pilot", {})
        # Exact private values are bound by the local provenance manifest above;
        # never embed a learner's scores or timing in public application code.
        first, supplement, maximum = pilot.get('first_visible_score'), pilot.get('supplemental_score'), pilot.get('max_score')
        if not all(isinstance(v,(int,float)) and not isinstance(v,bool) for v in (first,supplement,maximum)) or not 0 <= first <= supplement <= maximum or pilot.get('verified_net_seconds') is not None:
            errors.append("PILOT_PROVENANCE_CONFLICT")
        if any(pilot.get(k, 0) != 0 for k in ("verified_h0", "verified_m4", "instructor_signatures")):
            errors.append("PILOT_CERTIFICATION_MUST_REMAIN_ZERO")
        if set(pilot.get("specialties", {}).values()) != {"PROMPT_GENERATED_NOT_TRAINED"}:
            errors.append("PILOT_SPECIALTY_NOT_TRAINED")
        specialties = data.get("specialties", {})
        if not isinstance(specialties, dict) or not {"Q03", "Q06"} <= set(specialties):
            errors.append("Q03_Q06_EXECUTABLE_SPECIALTIES_REQUIRED")
        else:
            for key, specialty in specialties.items():
                if not isinstance(specialty, dict) or specialty.get("status") != "PLANNED" or not isinstance(specialty.get("steps"), list) or len(specialty["steps"]) < 3:
                    errors.append("INVALID_OR_PRETRAINED_SPECIALTY:" + key)
                    continue
                for step in specialty["steps"]:
                    if step.get("status") != "NOT_STARTED":
                        errors.append("SPECIALTY_STEP_MUST_NOT_BE_PRETRAINED:" + key)
                    if step.get("item_id") and step["item_id"] not in ids:
                        errors.append("UNKNOWN_SPECIALTY_ITEM:" + key)
        supply = {family: {"compound_candidates": sum(family in i.get("families", []) and str(i.get("difficulty", {}).get("claim", "")).startswith("R2") for i in curated), "repair_bridges": sum(family in i.get("families", []) and i.get("difficulty", {}).get("claim") == "R1_REPAIR" for i in curated), "certified_r2": 0} for family in FAMILIES}
        missing = [family for family, count in supply.items() if count["compound_candidates"] < 1]
        if missing:
            errors.append("MISSING_DAILY_FAMILY:" + ",".join(missing))
        report = dict(status="PASS" if not errors else "FAIL", scope="PRIVATE_LOCAL_FORMATIVE_EXACT_VERSION_ONLY", schema_version=SCHEMA_VERSION, bank_sha256=bank_sha256, manifest_sha256=manifest_sha256, original_items=len(original), curated_items=len(curated), nodes=len(nodes), tier2_frozen=sum(i.get("tier") == "TIER2" for i in original), mathematical_checks=checks, supply=supply, seven_day_fresh_supply="INSUFFICIENT_VERIFIED_ITEMS", certified_r2_items=0, human_reviews=0, h0_certified=0, production_certification="FROZEN", errors=errors, warnings=["INSUFFICIENT_VERIFIED_R2_ITEMS：现有14道常规题只是未校准形成性候选。", "七族各2道常规候选，不足以支持7天持续陌生训练；已见或题源不足时停止，不造通过。", "ChatGPT文件持有人可以查看教练包；文件工作流不提供服务端保密保证。"])
        report['extension_items']=len(extensions)
        report['extension_mathematical_checks']=[r for r in checks if r['id'] in {i['id'] for i in extensions}]
        report['mathematical_checks']=[r for r in checks if r['id'] in {i['id'] for i in curated}]
        report['mapping_warnings']=[{'id':i['id'],'issues':mapping_errors(i)} for i in curated if mapping_errors(i)]
        report['current_qualified_candidate_count']=len(curated)+len(extensions)
        report['certified_r2_items']=sum(calibration(i)['eligible_r2'] for i in curated+extensions)
        self._validation_cache = {cache_key: copy.deepcopy(report)}
        return report


def write_manifest(path: str | Path):
    """Explicit local publishing helper; this is hashing, never human signoff.

    Callers must first independently review/validate the new local bank. This
    function cannot invent a trusted signature and is not exposed as a shortcut
    by the training workflow.
    """
    path = Path(path).resolve()
    raw = path.read_bytes()
    data = _strict_json(raw.decode("utf-8-sig"))
    manifest = dict(schema_version="math2.private-bank-manifest.v1", bank_sha256=hashlib.sha256(raw).hexdigest(), item_payload_sha256={i["id"]: digest(i) for i in data["items"]}, nodes_sha256=digest(data["nodes"]), pilot_sha256=digest(data.get("pilot")), sources_sha256=digest(data.get("sources")), specialties_sha256=digest(data.get("specialties")), scope="FORMATIVE_HASH_BINDING_NOT_HUMAN_REVIEW", human_reviews=0, h0_eligible=False)
    target = manifest_path(path)
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return target
