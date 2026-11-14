"""Authenticate separate original forward batches without inventing an origin.

Every P/O keeps its existing immutable receipt, provenance and cutoff checks.
The returned union is a derived evaluation context, never a saved forecast.
"""
from copy import deepcopy

from .actions_contract import digest
from .all_existing_model_future_baseline import validate_pin
from .all_existing_model_receipt import _verified_private_pairs_artifact
from .all_existing_model_cash_pdca_origin import verify_origin_artifact


def need(ok,reason):
    if not ok:raise ValueError('ALL_MODEL_FUTURE_BATCHES_'+reason)


def validate_forecast_batches(value):
    need(type(value) is list and 1<=len(value)<=4,'BOUNDED_BATCHES')
    ids=set()
    for batch in value:
        need(type(batch) is dict and set(batch)=={'future_artifact','origin_artifact'},'BATCH_FIELDS')
        for pin in batch.values():
            validate_pin(pin);need(pin['id'] not in ids,'DISTINCT_ARTIFACTS');ids.add(pin['id'])
        future=batch['future_artifact'];origin=batch['origin_artifact']
        need(all(future[k]==origin[k] for k in ('run_id','head_sha')),'PAIR_RUN_HEAD')
    return deepcopy(value)


def admit_batch_origins(batches,archives,*,now,key=None):
    """Verify each original P/O, then require disjoint complete sports and F30."""
    batches=validate_forecast_batches(batches)
    need(type(archives) is list and len(archives)==len(batches),'BATCH_ARCHIVES')
    contexts=[]
    for pins,archive in zip(batches,archives,strict=True):
        need(type(archive) is dict and set(archive)=={'future','origin'},'ARCHIVE_FIELDS')
        for name,pin_name in (('future','future_artifact'),('origin','origin_artifact')):
            item=archive[name];pin=pins[pin_name]
            need(type(item) is dict and set(item)=={'raw','metadata'} and type(item['raw']) is bytes and
                type(item['metadata']) is dict,'ARCHIVE_MEMBER')
            meta=item['metadata'];run=meta.get('workflow_run',{})
            need(type(run) is dict and (meta.get('id'),meta.get('digest'),run.get('id'),run.get('head_sha'))==
                (pin['id'],pin['digest'],pin['run_id'],pin['head_sha']),'ACTUAL_PIN')
        saved=archive['future'];original=archive['origin'];pin=pins['future_artifact']
        admission,parts=_verified_private_pairs_artifact(saved['raw'],saved['metadata'],now=now,
            expected_run_id=pin['run_id'],expected_head_sha=pin['head_sha'],key=key)
        origin=verify_origin_artifact(original['raw'],original['metadata'],saved['raw'],saved['metadata'],
            admission,parts,now=now,candidate_cell_count=30)
        contexts.append(dict(pins=deepcopy(pins),admission=admission,records=parts,origin=origin))
    return _bind_admitted_batches(contexts)


def _bind_admitted_batches(contexts):
    """Post-authentication invariants for RAW admission or sealed PDCA replay.

    This is not an artifact admission API. Its caller must have authenticated
    every original record and origin through the existing readers first.
    """
    from scripts.all_existing_model_native_future import V3_CELLS
    need(type(contexts) is list and 1<=len(contexts)<=4,'BOUNDED_CONTEXTS')
    validate_forecast_batches([item['pins'] for item in contexts])
    records=[];seen=set();source_pins={};candidate=None
    for context in contexts:
        need(type(context) is dict and set(context)=={'pins','admission','records','origin'},'CONTEXT_FIELDS')
        parts=context['records'];origin=context['origin']
        need(type(parts) is list and 0<len(parts)<=30,'CONTEXT_RECORDS')
        cells={p['cell_key'] for p in parts}
        need(len(cells)==len(parts) and not seen&cells,'DISJOINT_CELLS')
        for sport,expected in V3_CELLS.items():
            present={cell for cell in cells if cell.startswith(sport+'/')}
            need(not present or present==expected,'COMPLETE_PRESENT_SPORT')
        binding=dict(training=parts[0]['training'],candidate_receipt=parts[0]['training_receipt'],
                     owner_research_record=origin['source_audit']['owner_research_record'])
        if candidate is None:candidate=deepcopy(binding)
        else:need(candidate==binding,'SAME_EXACT_F30_CANDIDATE_AND_OWNER')
        for source in origin['manifest']['source_input_artifacts']:
            need(source['id'] not in source_pins or source_pins[source['id']]==source,'SOURCE_PIN_CONFLICT')
            source_pins[source['id']]=deepcopy(source)
        records.extend(parts);seen|=cells
    expected=set().union(*V3_CELLS.values())
    need(len(records)==30 and seen==expected,'EXACT_DISJOINT_THIRTY_UNION')
    need(len(source_pins)<=16,'SOURCE_PIN_BOUND')
    return dict(batches=contexts,records=records,training_sha256=candidate['training']['training_sha256'],
        candidate_receipt=deepcopy(candidate['candidate_receipt']),
        owner_record_sha256=digest(candidate['owner_research_record']),candidate_context_sha256=digest(candidate),
        forecast_counts_by_sport={sport:len(cells) for sport,cells in V3_CELLS.items()},
        source_input_artifacts=[source_pins[ident] for ident in sorted(source_pins)])
