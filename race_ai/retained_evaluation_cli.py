"""Private retained-prediction audit CLI; no source fetching or model imports.

Origin and label-request descriptors are explicitly outcome-free metadata.
Expected descriptor/policy/report digests use compact sorted UTF-8 JSON with
no trailing newline. File pins hash the exact original bytes. Only the lazy
reserved reader opens label paths. Import and read times use current UTC;
there is no backdating flag. Stdout contains metadata, never private rows.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

from .retained_prediction_audit import (MAX_BYTES, ROLES, RetainedAuditError,
    RetainedAuditJournal, canonical, decode, digest, moment, regular_bytes,
    require, _create, _directory)


class CliError(ValueError):
    pass


class SafeParser(argparse.ArgumentParser):
    def error(self, _message):
        raise CliError('INVALID_ARGUMENTS')


def sha_argument(value):
    if not re.fullmatch('[0-9a-f]{64}',value):
        raise argparse.ArgumentTypeError('canonical SHA256 required')
    return value


def parser():
    root = SafeParser(description=__doc__)
    commands = root.add_subparsers(dest='command',required=True,parser_class=SafeParser)
    for operation in ('import','observe','append','report'):
        sub = commands.add_parser(operation)
        sub.add_argument('--root',required=True,type=Path,help='same trusted private registry used by EvaluationJournal')
        sub.add_argument('--audit',required=True)
        if operation == 'import':
            sub.add_argument('--origin',required=True,type=Path,help='outcome-free six-file descriptor')
            sub.add_argument('--expected-origin-request-sha',required=True,type=sha_argument)
            sub.add_argument('--policy',required=True,type=Path)
            sub.add_argument('--expected-policy-sha',required=True,type=sha_argument)
        else:
            sub.add_argument('--expected-import-sha',required=True,type=sha_argument)
        if operation in ('observe','append'):
            sub.add_argument('--label-request',required=True,type=Path,help='outcome-free selected path/identity/byte-pin descriptor')
            sub.add_argument('--expected-request-sha',required=True,type=sha_argument)
        if operation == 'append':
            sub.add_argument('--batch-number',required=True,type=int)
            sub.add_argument('--expected-report-sha',required=True,type=sha_argument)
        if operation == 'report':
            sub.add_argument('--through-batch',type=int,help='explicit completed batch; omitted means latest, including pending failures')
            sub.add_argument('--expected-report-sha',type=sha_argument)
            sub.add_argument('--output',type=Path,help='create-only private full report')
    return root


def _descriptor(path, expected):
    value = decode(regular_bytes(path))
    require(digest(value) == expected, 'DESCRIPTOR_HASH_CHANGED')
    return value


def _origin(request):
    require(type(request) is dict and set(request) == {'schema','files'} and
            request['schema'] == 'RACE_AI_RETAINED_ORIGIN_REQUEST_V1' and type(request['files']) is dict and
            set(request['files']) == ROLES, 'ORIGIN_REQUEST_FIELDS')
    paths = []
    for value in request['files'].values():
        require(type(value) is dict and set(value) == {'path','sha256'} and type(value['path']) is str and
                1 <= len(value['path']) <= 4096 and '\x00' not in value['path'] and
                type(value['sha256']) is str and re.fullmatch('[0-9a-f]{64}',value['sha256']), 'ORIGIN_REQUEST_FIELDS')
        paths.append(str(Path(value['path']).resolve()))
    require(len(set(paths)) == 6, 'ORIGIN_PATH_ALIAS')
    files = {}; total = 0
    for role,entry in request['files'].items():
        content = regular_bytes(entry['path']); total += len(content)
        require(total <= MAX_BYTES, 'ORIGIN_TOTAL_SIZE')
        files[role] = content
    return files, {role:entry['sha256'] for role,entry in request['files'].items()}


def _label_reader(request):
    # Constructing this closure opens/hashes no label file.
    def read():
        items = []; total = 0
        for item in request['observations']:
            raw = regular_bytes(item['path']); total += len(raw)
            require(total <= MAX_BYTES, 'LABEL_TOTAL_SIZE')
            items.append({'expected_sha256':item['file_sha256'],'raw':raw})
        return items
    return read


def _summary(report):
    first = report['models'][0]
    return {'report_sha256':digest(report),'import_sha256':report['import_sha256'],
        'mode':report['mode'],'cohort_role':report['cohort_role'],'final_test_eligible':False,
        'cohort_races':report['cohort_races'],'model_slots':report['model_slots'],
        'models':len(report['models']),'through_batch':report['through_batch'],
        'label_observations':report['label_observations'],'known_results':first['known_results'],
        'unobserved_results':first['unobserved_results'],'observed_unscored_results':first['observed_unscored_results'],
        'unknown_results':first['unknown_results'],'excluded_results':first['excluded_results']}


def execute(args):
    journal = RetainedAuditJournal(args.root,args.audit)
    if args.command == 'import':
        request = _descriptor(args.origin,args.expected_origin_request_sha)
        policy = _descriptor(args.policy,args.expected_policy_sha)
        require(type(policy) is dict and moment(policy.get('declared_at')) <= datetime.now(timezone.utc), 'POLICY_CLOCK')
        files,pins = _origin(request)
        imported = journal.import_bundle(files,expected_sha256=pins,policy=policy,expected_policy_sha256=args.expected_policy_sha)
        result = {'import_sha256':imported['import_sha256'],'policy_sha256':imported['policy_sha256'],
            'imported_at':imported['imported_at'],'cohort_races':len(imported['origin']['races']),
            'models':len(imported['origin']['models']),'model_slots':3192,
            'potentially_exposed_physical_races':imported['potentially_exposed_physical_races'],
            'potentially_exposed_registry_keys':imported['potentially_exposed_registry_keys'],
            'mode':imported['mode'],'cohort_role':'DEVELOPMENT_AUDIT','final_test_eligible':False}
    elif args.command in ('observe','append'):
        request = _descriptor(args.label_request,args.expected_request_sha)
        options = {'expected_import_sha256':args.expected_import_sha,'label_request':request,
                   'expected_request_sha256':args.expected_request_sha}
        if args.command == 'observe':
            report = journal.observe(_label_reader(request),**options)
        else:
            report = journal.append_results(_label_reader(request),batch_number=args.batch_number,
                expected_report_sha256=args.expected_report_sha,**options)
        result = _summary(report)
    else:
        report = journal.read_report(expected_import_sha256=args.expected_import_sha,through_batch=args.through_batch)
        require(args.expected_report_sha is None or digest(report) == args.expected_report_sha, 'EXPECTED_REPORT_CHANGED')
        if args.output is not None:
            _directory(args.output.parent)
            _create(args.output,report)
        result = {**_summary(report),'selection':'LATEST' if args.through_batch is None else 'EXPLICIT_COMPLETED_BATCH',
                  'report_exported':args.output is not None}
    return {'status':'OK','operation':args.command,**result}


def main(argv=None):
    try:
        result = execute(parser().parse_args(argv))
    except CliError as exc:
        code = exc.args[0]
    except FileExistsError:
        code = 'FILE_ALREADY_EXISTS'
    except FileNotFoundError:
        code = 'FILE_NOT_FOUND'
    except OSError:
        code = 'FILE_ACCESS_ERROR'
    except (RetainedAuditError,ValueError,TypeError,KeyError,IndexError,OverflowError,RecursionError,UnicodeError):
        code = 'RETAINED_AUDIT_REJECTED'
    else:
        print(json.dumps(result,sort_keys=True,allow_nan=False))
        return 0
    print(json.dumps({'status':'ERROR','error':code},sort_keys=True),file=sys.stderr)
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
