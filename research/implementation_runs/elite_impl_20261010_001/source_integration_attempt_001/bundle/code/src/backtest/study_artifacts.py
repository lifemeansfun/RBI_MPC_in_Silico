"""Portable, immutable scientific inputs; raw observations remain source evidence."""
import base64
import hashlib
import json
from pathlib import Path

from src.infra.evidence import content_hash, file_hash, write_immutable
from src.infra.exceptions import ArtifactIntegrityError


def strict_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'Duplicate JSON key {key}')
            result[key] = value
        return result
    def finite(value):
        raise ValueError(f'Nonfinite evidence {value}')
    try:
        return json.loads(Path(path).read_text(), object_pairs_hook=unique, parse_constant=finite)
    except (OSError, ValueError, TypeError) as exc:
        raise ArtifactIntegrityError(f'Missing or invalid scientific input: {path}') from exc


def prepare_inputs(snapshots, truth, config, personas, corpus_path, root, *, research_mode):
    root = Path(root).resolve()
    sources = {}
    def add(path, expected_hash=None):
        path = Path(path).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ArtifactIntegrityError(f'Missing or outside-project source {path}')
        payload = path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if expected_hash is not None and digest != expected_hash:
            raise ArtifactIntegrityError(f'Source changed before study freeze: {path}')
        sources[str(path.relative_to(root))] = {'sha256': digest, 'encoding': 'base64',
                                              'bytes': base64.b64encode(payload).decode('ascii')}
    def observation(item):
        add(root / item.source_file, item.source_sha256)
        for child in item.input_evidence:
            observation(child)
    for snapshot in snapshots:
        for item in snapshot.observations:
            observation(item)
    for row in truth:
        if research_mode or row.get('source_file'):
            add(root / row['source_file'], row['source_sha256'])
    corpus = None
    if research_mode:
        corpus = strict_json(corpus_path)
        add(corpus_path)
        for member in corpus['members'].values():
            for row in member['corpus_sources']:
                for kind in ('source', 'statement'):
                    add(root / row[f'{kind}_file'], row[f'{kind}_sha256'])
    return {'snapshots.json': [s.model_dump(mode='json') for s in snapshots],
            'truth.json': truth, 'config.json': config, 'personas.json': personas,
            'corpus_manifest.json': corpus, 'raw_sources.json': sources}


def persist_inputs(directory, inputs, *, replay):
    for name, payload in inputs.items():
        write_immutable(Path(directory) / name, payload, replay=replay)


def read_inputs(directory, expected_hashes):
    names = {'snapshots.json', 'truth.json', 'config.json', 'personas.json',
             'corpus_manifest.json', 'raw_sources.json'}
    if set(expected_hashes) != names:
        raise ArtifactIntegrityError('Scientific input manifest is incomplete')
    inputs = {name: strict_json(Path(directory) / name) for name in names}
    if {name: content_hash(value) for name, value in inputs.items()} != expected_hashes:
        raise ArtifactIntegrityError('Frozen scientific input content differs from manifest')
    for name, record in inputs['raw_sources.json'].items():
        path = Path(name)
        if path.is_absolute() or '..' in path.parts or record['encoding'] != 'base64':
            raise ArtifactIntegrityError('Invalid portable source identity')
        try:
            payload = base64.b64decode(record['bytes'], validate=True)
        except (ValueError, TypeError) as exc:
            raise ArtifactIntegrityError('Invalid raw source encoding') from exc
        if hashlib.sha256(payload).hexdigest() != record['sha256']:
            raise ArtifactIntegrityError('Portable source bytes are corrupt')
    return inputs


def verify_observation_bundle(snapshot, sources):
    def verify(item):
        if item.source_file not in sources or sources[item.source_file]['sha256'] != item.source_sha256:
            raise ArtifactIntegrityError('Observation has missing or mismatched portable source bytes')
        for child in item.input_evidence:
            verify(child)
    for item in snapshot.observations:
        verify(item)
