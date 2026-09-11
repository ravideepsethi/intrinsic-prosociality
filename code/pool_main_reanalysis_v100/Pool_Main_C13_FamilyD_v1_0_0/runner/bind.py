"""Bind only sample authorities and outcome-blind support checks."""
from __future__ import annotations
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from runner import common

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError('Source-binding rule did not match exactly once: '+old[:80])
    return text.replace(old,new,1)


def constants(text, values):
    tree=ast.parse(text); replacements=[]
    for name,value in values.items():
        matches=[n for n in tree.body if isinstance(n,ast.Assign) and len(n.targets)==1
                 and isinstance(n.targets[0],ast.Name) and n.targets[0].id==name]
        if len(matches)!=1:
            raise RuntimeError('Ambiguous authority constant: '+name)
        node=matches[0]; replacements.append((node.lineno-1,node.end_lineno,f'{name} = {value!r}\n'))
    lines=text.splitlines(keepends=True)
    for start,stop,value in sorted(replacements,reverse=True):
        lines[start:stop]=[value]
    return ''.join(lines)


def render(fair_rows=15207423, fair_kind=419463, all_rows=41534331, all_kind=570091):
    bindings=json.loads((ROOT/'authority/SOURCE_BINDINGS.json').read_text())
    for binding in bindings:
        if common.sha256_file(ROOT/binding['path'])!=binding['sha256']:
            raise RuntimeError('Frozen source changed: '+binding['path'])
    original=(ROOT/'source/campaign1_c13_v104.py').read_text()
    text=constants(original,{'EXPECTED_FAIR_ROWS':fair_rows,'EXPECTED_FAIR_KIND_DRAWS':fair_kind,
                             'EXPECTED_ALL_STAGE07_KIND_DRAWS':all_kind})
    edits=[(
        'cached-new-sample-support-invariant',
        '        if int(saved.get("primary_supported_rows", -1)) != EXPECTED_PRIMARY_SUPPORTED_ROWS:\n            raise RuntimeError("Frozen C13 support no longer matches the v1.0.2 reconstruction")',
        '        if not 0 <= int(saved.get("primary_supported_rows", -1)) <= EXPECTED_FAIR_ROWS:\n            raise RuntimeError("Invalid frozen pool-main C13 support")'),(
        'new-sample-outcome-blind-support-freeze',
        '''    if (
        qa[0] != EXPECTED_FAIR_ROWS
        or qa[0] != qa[1]
        or qa[2] != EXPECTED_PRIMARY_SUPPORTED_ROWS
        or qa[9] != 0
        or int(qa[10]) != EXPECTED_PRIMARY_OTHER_N28_MIN
        or float(qa[11]) != EXPECTED_PRIMARY_OTHER_N28_P10
        or float(qa[12]) != EXPECTED_PRIMARY_OTHER_N28_MEDIAN
    ):
        raise RuntimeError(
            "C13 frozen support failed to reproduce the corrected v1.0.2 reconstruction: "
            f"rows={qa[0]} unique={qa[1]} primary={qa[2]} "
            f"expected={EXPECTED_PRIMARY_SUPPORTED_ROWS} negative={qa[9]} "
            f"min/p10/median={qa[10:13]}"
        )''',
        '''    if (
        qa[0] != EXPECTED_FAIR_ROWS or qa[0] != qa[1] or qa[9] != 0
        or any(value is None or not 0 <= int(value) <= EXPECTED_FAIR_ROWS for value in qa[2:9])
        or any(value is None or not math.isfinite(float(value)) or float(value) < 0 for value in qa[10:13])
    ):
        raise RuntimeError(f"Pool-main C13 denominator invariants failed: {qa}")'''),(
        'new-sample-support-receipt-label',
        '''        "support_authority": "outcome-blind v1.0.2 exact reconstruction",
        "superseded_wave0_supported_rows": WAVE0_PRIMARY_SUPPORTED_ROWS,
        "wave0_minus_corrected_rows": (
            WAVE0_PRIMARY_SUPPORTED_ROWS - EXPECTED_PRIMARY_SUPPORTED_ROWS
        ),''',
        '''        "support_authority": "pool-main rebuild, frozen before new ambient numerator",
        "old_sample_supported_rows_for_provenance_only": EXPECTED_PRIMARY_SUPPORTED_ROWS,
        "old_sample_support_count_not_enforced_on_new_sample": True,''')]
    for label,old,new in edits:
        text=replace_once(text,old,new)
    shared_original=(ROOT/'source/campaign1_nonprofile_common_v102.py').read_text()
    shared=constants(shared_original,{'EXPECTED_STAGE07_ROWS':all_rows,'EXPECTED_STAGE07_FAIR_ROWS':fair_rows})
    for value in (text,shared): ast.parse(value)
    receipt={'status':'C13_POOL_SAMPLE_SOURCE_BOUND','original_sources':bindings,
             'constant_changes':{'EXPECTED_FAIR_ROWS':fair_rows,'EXPECTED_FAIR_KIND_DRAWS':fair_kind,
                                'EXPECTED_ALL_STAGE07_KIND_DRAWS':all_kind,'EXPECTED_STAGE07_ROWS':all_rows,
                                'EXPECTED_STAGE07_FAIR_ROWS':fair_rows},
             'exact_edits':[{'label':label,'old':old,'new':new} for label,old,new in edits],
             'model_equations_controls_fixed_effects_and_retry_policy_changed':False,
             'support_SQL_changed':False,'original_execute_and_self_test_not_used_as_production_entrypoints':True,
             'rendered_sha256':{name:hashlib.sha256(value.encode()).hexdigest() for name,value in
                                [('campaign1_c13_v104.py',text),('campaign1_nonprofile_common_v102.py',shared)]}}
    return {'campaign1_c13_v104.py':text,'campaign1_nonprofile_common_v102.py':shared},receipt


def load_rendered(directory, rendered):
    directory.mkdir(parents=True,exist_ok=True)
    for name,text in rendered.items():
        path=directory/name
        if path.exists() and path.read_text()!=text:
            raise RuntimeError('Existing execution source differs: '+name)
        if not path.exists(): common.atomic_text(path,text)
    def load(name,path):
        spec=importlib.util.spec_from_file_location(name,path)
        module=importlib.util.module_from_spec(spec)
        sys.modules[name]=module;spec.loader.exec_module(module)
        return module
    shared=load('campaign1_nonprofile_common_v102',directory/'campaign1_nonprofile_common_v102.py')
    c13=load('pool_main_bound_c13',directory/'campaign1_c13_v104.py')
    return c13,shared
