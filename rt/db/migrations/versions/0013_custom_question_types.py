"""Rimuove i tipi fissi dai documenti del pool e le etichette obsolete."""
import hashlib
import json
import time

from alembic import op
import sqlalchemy as sa

revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade():
    from rt.recall.migration import migrate_bank, legacy_labels, POSITIVE, seeded_types
    connection = op.get_bind()
    # Le lezioni senza cartella hanno le vecchie etichette solo in lesson_files.
    found = {k: set() for k in POSITIVE}
    for subject, content in connection.execute(sa.text(
            "SELECT l.materia, f.content FROM lesson_files f JOIN lessons l ON l.id=f.lesson_id "
            "WHERE f.name='section_labels.json'")):
        if subject and content:
            labels = json.loads(content)
            for kind, values in POSITIVE.items():
                if any((r.get('override_' + kind) or r.get(kind)) in values for r in labels.values() if isinstance(r, dict)):
                    found[kind].add(subject)
    if any(found.values()):
        from rt.services.config_service import general_config_path, read_yaml, write_yaml_atomic
        path = general_config_path()
        data = read_yaml(path)
        registry = data.setdefault('recall', {}).setdefault('custom_types', [])
        registered = {t['id'] for t in registry}
        registry.extend(t for t in seeded_types(found) if t['id'] not in registered)
        write_yaml_atomic(path, data)
    documents = sa.table('state_documents', sa.column('key', sa.String), sa.column('payload', sa.JSON))
    for key, payload in connection.execute(sa.select(documents.c.key, documents.c.payload)):
        if not isinstance(payload, dict):
            continue
        changed = migrate_bank(payload) if key.endswith('recall_questions.json') else (
            {} if key.endswith('section_labels.json') and legacy_labels(payload) else payload)
        if changed != payload:
            connection.execute(documents.update().where(documents.c.key == key).values(payload=changed))
    files = sa.table('lesson_files', sa.column('id', sa.Integer), sa.column('name', sa.String),
                     sa.column('content', sa.LargeBinary), sa.column('size', sa.Integer),
                     sa.column('sha256', sa.String), sa.column('mtime', sa.Float))
    for identifier, name, content in connection.execute(sa.select(files.c.id, files.c.name, files.c.content)):
        if name not in ('recall_questions.json', 'section_labels.json') or not content:
            continue
        payload = json.loads(content)
        changed = migrate_bank(payload) if name == 'recall_questions.json' else ({} if legacy_labels(payload) else payload)
        if changed != payload:
            encoded = json.dumps(changed, ensure_ascii=False, indent=2).encode()
            connection.execute(files.update().where(files.c.id == identifier).values(
                content=encoded, size=len(encoded), sha256=hashlib.sha256(encoded).hexdigest(), mtime=time.time()))


def downgrade():
    # La rimozione delle domande autorizzata dal piano non è reversibile.
    pass
