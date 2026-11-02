"""Explicit offline candidate review into a new private bank, never overwrite."""
from pathlib import Path
from .bank import Bank, write_manifest, manifest_path
from .mathsafe import item_digest, validate_math
from .quality import mapping_errors, duplicate_groups
from .util import load_json, write_json


def review_candidate(item):
    errors=[]
    if item.get('source')!='LOCAL_REVIEWED_EXTENSION':errors.append('EXPLICIT_EXTENSION_SOURCE_REQUIRED')
    if item.get('h0_eligible') is not False or item.get('teacher_review')!='NOT_PERFORMED':
        errors.append('NO_TEACHER_OR_H0_AUTHORIZATION')
    if item.get('difficulty',{}).get('calibration_status')!='UNKNOWN':errors.append('UNCALIBRATED_SOURCE_REQUIRED')
    if item_digest(item)!=item.get('version_hash'):errors.append('VERSION_MISMATCH')
    if item.get('release_status')!='FORMATIVE_MACHINE_CHECKED':errors.append('FORMATIVE_SCOPE_REQUIRED')
    if not item.get('node_fields') or not item.get('training_roles'):errors.append('SUBQUESTION_AND_ROLE_REQUIRED')
    errors.extend(mapping_errors(item))
    try:math=validate_math(item)
    except Exception as exc:
        math=None;errors.append('INDEPENDENT_MATH:'+str(exc))
    return {'item_id':item.get('id'),'status':'FAIL' if errors else 'PASS','errors':errors,'math':math,
            'difficulty':'UNCALIBRATED','teacher_review':'NOT_PERFORMED'}


def review_candidates(bank, source, output):
    target=Path(output).resolve()
    if target==bank.path or target.exists() or manifest_path(target).exists():
        raise ValueError('Candidate review requires a new output bank; existing versions are immutable')
    proposals=load_json(source)
    if not isinstance(proposals,list) or not proposals or not all(isinstance(i,dict) for i in proposals):
        raise ValueError('Provide a nonempty JSON list of full candidate records')
    report=[review_candidate(i) for i in proposals]
    data,_=bank._read();ids=[i['id'] for i in data['items']+proposals]
    errors=[]
    if len(ids)!=len(set(ids)):errors.append('DUPLICATE_ITEM_ID_USE_NEW_VERSION_ID')
    if any(r['status']=='FAIL' for r in report):errors.append('CANDIDATE_QA_FAILED')
    if bank.validate()['status']!='PASS':errors.append('BASE_BANK_QA_FAILED')
    if errors:return {'status':'FAIL','errors':errors,'candidate_reviews':report}
    data['items']+=proposals
    # Validate in an isolated temporary directory before publishing the artifact.
    import tempfile
    with tempfile.TemporaryDirectory(prefix='math2_candidate_review_') as folder:
        staged=Path(folder)/'private_catalog.json';write_json(staged,data);write_manifest(staged)
        qa=Bank(staged).validate()
        if qa['status']!='PASS':return {'status':'FAIL','errors':qa['errors'],'candidate_reviews':report}
        from .util import atomic_bytes
        atomic_bytes(target,staged.read_bytes());atomic_bytes(manifest_path(target),manifest_path(staged).read_bytes())
    return {'status':'PASS','output_bank':str(target),'candidate_reviews':report,
            'semantic_duplicate_warnings':duplicate_groups(data['items']),
            'activation':'NOT_ACTIVATED; select explicitly with --bank','h0_certified':False}
