"""Note di versione installate, condivise dalla release e dall'API."""
from pathlib import Path
import re

HEADER = re.compile(r"^## (?P<version>\d+\.\d+\.\d+\S*) — (?P<date>\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE)


def release_sections(text: str) -> list[tuple[str, str, str]]:
    """Versione, data e Markdown di ogni sezione, nell'ordine del file."""
    matches = list(HEADER.finditer(text))
    result = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        # Il rimando alle release precedenti non appartiene alle note della versione.
        body = text[match.end():end].split("\nPer le versioni precedenti:", 1)[0].strip()
        result.append((match['version'], match['date'], body))
    return result


def release_notes(text: str, version: str) -> str:
    for current, _date, body in release_sections(text):
        if current == version:
            return body + "\n"
    raise ValueError(f"CHANGELOG.md: manca la sezione della versione {version}")


def parse_changelog(text: str) -> list[dict]:
    """Solo gruppi e punti elenco: la SPA li mostra come testo semplice."""
    result = []
    for version, date, body in release_sections(text):
        groups = []
        current = None
        for line in body.splitlines():
            if line.startswith('### '):
                current = {'title': line[4:].strip(), 'items': []}
                groups.append(current)
            elif current is not None and line.startswith('- '):
                current['items'].append(line[2:].strip())
            elif current is not None and line.startswith('  ') and current['items']:
                current['items'][-1] += ' ' + line.strip()
        result.append({'version': version, 'date': date, 'groups': groups})
    return result


def read_changelog(root: str | Path) -> list[dict]:
    try:
        text = (Path(root) / 'CHANGELOG.md').read_text(encoding='utf-8')
    except FileNotFoundError:
        return []
    return parse_changelog(text)
