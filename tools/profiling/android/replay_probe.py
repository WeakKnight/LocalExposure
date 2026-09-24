"""Create an output-identical pass-replay bundle for bottleneck diagnosis.

Run the resulting bundle with activity --hdr-producer --joint-submission.
Replay cost includes an extra dispatch and barrier and benefits from warm caches;
it is not an exact decomposition of the original frame or an optimization.
"""
import argparse
import copy
import json
import shutil
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--stage', choices=['reduce_setup', 'reconstruct_guided',
                                           'apply_exposure_production', 'apply_pair'], required=True)
    parser.add_argument('--copies', type=int, default=2)
    args = parser.parse_args()
    if not 2 <= args.copies <= 8:
        parser.error('copies must be between 2 and 8')
    manifest = json.loads((args.bundle / 'manifest.json').read_text())
    labels = ({'apply_exposure_production', 'tonemap_baseline'}
              if args.stage == 'apply_pair' else {args.stage})
    matches = [p for p in manifest['passes'] if p['label'] in labels]
    if len(matches) != len(labels):
        raise ValueError('Expected exactly one pass per target label')
    # These production entries write outputs independent of their previous values.
    for target in matches:
        reads = {d['resource'] for d in target['descriptors'] if d['type'] == 2}
        writes = {d['resource'] for d in target['descriptors'] if d['type'] == 3}
        if not writes or reads & writes:
            raise ValueError('Replay requires separate sampled inputs and storage outputs')
    passes = []
    for p in manifest['passes']:
        passes.append(p)
        if p['label'] in labels:
            for i in range(1, args.copies):
                replay = copy.deepcopy(p)
                replay['label'] += f'_replay{i}'
                passes.append(replay)
    manifest['passes'] = passes
    manifest['diagnostic_replay'] = dict(stage=args.stage, copies=args.copies,
        source_bundle=str(args.bundle.resolve()),
        note='Diagnostic only. Consecutive identical dispatches with normal barriers.')
    shutil.copytree(args.bundle, args.out)
    (args.out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    main()
