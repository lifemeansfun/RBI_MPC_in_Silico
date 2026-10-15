"""Verify dated corpus bytes and fitted persona fields before research generation."""
import json
from datetime import date, datetime
from pathlib import Path

from src.infra.evidence import file_hash
from src.infra.exceptions import GenerationProvenanceError
from src.schemas.persona_schema import MemberPersona

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def verify_personas(personas, cutoff, *, source_root=None, corpus_manifest_path=None):
    root = Path(source_root or PROJECT_ROOT).resolve()
    requested_cutoff = cutoff
    if isinstance(cutoff, datetime):
        if cutoff.tzinfo is None:
            raise GenerationProvenanceError('Persona prediction cutoff needs a timezone')
        cutoff = cutoff.date().isoformat()
    if not isinstance(cutoff, str) or date.fromisoformat(cutoff).isoformat() != cutoff:
        raise GenerationProvenanceError('Persona prediction cutoff must be an ISO calendar day')
    validated = [MemberPersona.model_validate(p.model_dump()) for p in personas]
    if not validated or len({p.member_id for p in validated}) != len(validated):
        raise GenerationProvenanceError('Distinct nonempty research personas required')
    # Additive portable v3 support. Legacy dated-lexical-v2 manifests retain
    # their existing lookup and fit semantics below. The rolling adapter
    # reconstructs all v3 fields from the explicitly bound portable raw bytes.
    if corpus_manifest_path:
        path = Path(corpus_manifest_path)
        if path.is_file():
            try:
                manifest = json.loads(path.read_text())
            except (ValueError, OSError) as exc:
                raise GenerationProvenanceError('Unreadable persona corpus manifest') from exc
            if manifest.get('version') == 'dated-lexical-rolling-v3':
                if source_root is None:
                    raise GenerationProvenanceError('Rolling personas require an explicit portable source_root')
                from src.persona_engine.executable_rolling import verify_rolling_manifest
                return verify_rolling_manifest(validated, source_root=root,
                    corpus_manifest_path=path, cutoff=requested_cutoff)
    manifests = {}
    for persona in validated:
        if (persona.provenance_status != 'dated_corpus' or not persona.calibration_cutoff
                or persona.calibration_cutoff > cutoff):
            raise GenerationProvenanceError('Undated, assumed or future corpus cannot be research persona evidence')
        path = Path(corpus_manifest_path) if corpus_manifest_path else (
            root / 'personas' / f'calibration_{persona.calibration_cutoff}_v2' / 'corpus_manifest.json')
        if not path.is_file() or file_hash(path) != persona.corpus_manifest_hash:
            raise GenerationProvenanceError('Missing or changed persona corpus manifest')
        if path not in manifests:
            manifests[path] = json.loads(path.read_text())
        manifest = manifests[path]
        if manifest.get('calibration_cutoff') != persona.calibration_cutoff:
            raise GenerationProvenanceError('Persona and corpus cutoffs differ')
        member = manifest.get('members', {}).get(persona.member_id)
        if not member or not member.get('corpus_sources') or not member.get('meetings_count'):
            raise GenerationProvenanceError('Persona has no actual pre-cutoff corpus')
        fields = {'name': 'name', 'role': 'role', 'is_internal': 'is_internal',
                  'hawk_dove_score': 'calibrated_hawk_dove', 'stance_bias': 'stance_bias',
                  'voting_priority': 'voting_priority', 'biography': 'biography',
                  'key_themes': 'exemplar_quotes'}
        if any(getattr(persona, field) != member.get(key) for field, key in fields.items()):
            raise GenerationProvenanceError('Persona fields differ from their frozen corpus fit')
        if persona.system_prompt_override is not None:
            raise GenerationProvenanceError('An unregistered prompt override is not the frozen corpus fit')
        rows = member['corpus_sources']
        if len(rows) != member['meetings_count'] or len({r['decision_date'] for r in rows}) != len(rows):
            raise GenerationProvenanceError('Corpus source rows are duplicated or incomplete')
        for row in rows:
            decision = date.fromisoformat(row['decision_date']).isoformat()
            publication = date.fromisoformat(row['publication_date']).isoformat()
            if not decision <= publication < persona.calibration_cutoff:
                raise GenerationProvenanceError('Corpus statement is unavailable at calibration cutoff')
            for name in ('source', 'statement'):
                source = (root / row[f'{name}_file']).resolve()
                if (not source.is_relative_to(root) or not source.is_file()
                        or file_hash(source) != row[f'{name}_sha256']):
                    raise GenerationProvenanceError(f'Missing or changed persona {name} bytes')
    return validated
