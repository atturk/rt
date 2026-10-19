"""Docenti per materia, popolati dai metadati esistenti."""
from datetime import datetime
import os

import yaml

from alembic import op
import sqlalchemy as sa

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    # Il docente delle lezioni era solo in info.yaml (su disco o in lesson_files).
    if not any(column['name'] == 'docente' for column in sa.inspect(bind).get_columns('lessons')):
        op.add_column('lessons', sa.Column('docente', sa.String(256), nullable=False, server_default=''))
        for lesson_id, path in bind.execute(sa.text('SELECT id, path FROM lessons')).all():
            content = bind.execute(sa.text("SELECT content FROM lesson_files WHERE lesson_id=:id AND name='info.yaml'"),
                                   {'id': lesson_id}).scalar()
            try:
                if content is None:
                    for candidate in (os.path.join(path, 'info.yaml'), os.path.join(path, '_state', 'info.yaml')):
                        if os.path.isfile(candidate):
                            with open(candidate, 'rb') as stream:
                                content = stream.read()
                            break
                info = yaml.safe_load(content or '') or {}
                docente = str(info.get('docente') or '').strip() if isinstance(info, dict) else ''
            except (OSError, ValueError, yaml.YAMLError):
                docente = ''
            if docente:
                bind.execute(sa.text('UPDATE lessons SET docente=:docente WHERE id=:id'),
                             {'docente': docente, 'id': lesson_id})
    if sa.inspect(bind).has_table("subject_teachers"):
        return
    table = op.create_table("subject_teachers",
        sa.Column("materia", sa.String(256), primary_key=True),
        sa.Column("nome", sa.String(256), primary_key=True),
        sa.Column("creata_il", sa.DateTime(), nullable=False))
    subjects = {name.strip().casefold(): name.strip()
                for name in bind.execute(sa.text("SELECT nome FROM subjects")).scalars()}
    pairs = {}
    for name in ("lessons", "calendar_template_entries", "calendar_overrides"):
        for materia, docente in bind.execute(sa.text(f"SELECT materia, docente FROM {name}")):
            materia, docente = (materia or "").strip(), (docente or "").strip()
            if materia and docente:
                key = materia.casefold(), docente.casefold()
                subjects.setdefault(key[0], materia)
                pairs.setdefault(key, {"materia": subjects[key[0]], "nome": docente, "creata_il": datetime.now()})
    if pairs:
        bind.execute(table.insert(), list(pairs.values()))


def downgrade():
    op.drop_table("subject_teachers")
    op.drop_column('lessons', 'docente')
