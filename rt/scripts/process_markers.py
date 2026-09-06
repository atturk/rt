#!/usr/bin/env python3
"""
process_markers.py
Helper script per la skill 'rt'.
Operazioni supportate:
  init        <cartella>              — valida la cartella rt-setup e restituisce i metadati
  check-yaml  <file_trascritto>
  merge       <cartella> [output_file]
  append      <target_file> <source_file_o_testo>
  extract     <pre-elaborato.md> <cartella_destinazione>
  clean       <pre-elaborato.md> <output_pulito.md>
  rename      <cartella>              — rinomina file finale e cartella con il titolo accademico
  update-info <info.yaml> chiave1=valore1 [chiave2=valore2 ...]
"""

import sys
import re
import os
import json

TIMECODE_REGEX = r"(?:\d{1,2}:)?\d{1,2}:\d{2}"

def clean_text_markers(text):
    """Rimuove tutti i marker inline preservando il testo pulito."""
    cleaned = re.sub(rf"\s*\(\s*(?:⁉️|⚠️|⁉|⚠)\s*(?:AMB|ERR)\d+\s*{TIMECODE_REGEX}.*?\)", "", text)
    cleaned = re.sub(rf"\s*(?:⁉️|⚠️|⁉|⚠)\s*(?:AMB|ERR)\d+\s*{TIMECODE_REGEX}.*?(?=\s|$)", "", cleaned)
    cleaned = re.sub(r"\(\s*\)", "", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip()

def extract_focal_context(line, match_start, match_end, max_words_before=15, max_words_after=15):
    """Estrae una finestra contestuale pulita e mirata attorno al marker."""
    prefix_str = line[:match_start]
    suffix_str = line[match_end:]

    # Rimuove le parentesi tonde esterne se il marker era racchiuso in (...)
    if prefix_str.rstrip().endswith("(") and suffix_str.lstrip().startswith(")"):
        prefix_str = prefix_str.rstrip()[:-1]
        suffix_str = suffix_str.lstrip()[1:]

    text_before = clean_text_markers(prefix_str)
    text_after = clean_text_markers(suffix_str)

    words_before = text_before.split()
    words_after = text_after.split()

    focal_before = " ".join(words_before[-max_words_before:]) if len(words_before) > max_words_before else text_before
    focal_after = " ".join(words_after[:max_words_after]) if len(words_after) > max_words_after else text_after

    prefix = "..." if len(words_before) > max_words_before else ""
    suffix = "..." if len(words_after) > max_words_after else ""

    ctx = f"{prefix}{focal_before} {focal_after}{suffix}".strip()
    ctx = re.sub(r"\(\s*\)", "", ctx)
    ctx = re.sub(r"\s+([,.:;?!])", r"\1", ctx)
    return re.sub(r"\s{2,}", " ", ctx).strip()

def check_yaml(file_path):
    """Verifica deterministicamente la presenza e validità del frontmatter YAML iniziale."""
    if not os.path.exists(file_path):
        print(f"Errore: File '{file_path}' non trovato.", file=sys.stderr)
        sys.exit(1)

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            header_sample = "".join(f.readline() for _ in range(120))
    except Exception as e:
        print(f"Errore durante la lettura del file: {e}", file=sys.stderr)
        sys.exit(1)

    match = re.match(r"^\s*---\s*\n([\s\S]*?)\n---", header_sample)
    if not match:
        print("Mancante: nessun blocco frontmatter YAML ('---') trovato in testa al file.", file=sys.stderr)
        sys.exit(1)

    yaml_block = match.group(1)
    data = {}

    try:
        import yaml
        parsed = yaml.safe_load(yaml_block)
        if isinstance(parsed, dict):
            data = parsed
    except Exception:
        for line in yaml_block.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                k, v = line.split(":", 1)
                data[k.strip().lower()] = v.strip().strip("\"'")

    date_val = str(data.get("data", "")).strip().strip("\"'")
    materia_val = str(data.get("materia", "")).strip().strip("\"'")
    titolo_val = str(data.get("titolo", "")).strip().strip("\"'")
    argomenti_raw = data.get("argomenti", [])

    if not date_val or not re.match(r"^\d{4}-\d{2}-\d{2}$", date_val):
        print(f"Non valido: campo 'data' mancante o non in formato AAAA-MM-GG (rilevato: '{date_val}').", file=sys.stderr)
        sys.exit(1)

    if not materia_val:
        print("Non valido: campo 'materia' mancante o vuoto.", file=sys.stderr)
        sys.exit(1)

    argomenti_list = []
    if isinstance(argomenti_raw, list):
        argomenti_list = [str(a).strip() for a in argomenti_raw if str(a).strip()]
    elif isinstance(argomenti_raw, str) and argomenti_raw:
        argomenti_list = [a.strip() for a in argomenti_raw.split(",") if a.strip()]

    arg_str = ", ".join(argomenti_list) if argomenti_list else (titolo_val if titolo_val else "Argomenti")
    safe_arg_str = re.sub(r'[/\\:*?"<>|]', " ", arg_str)
    safe_arg_str = re.sub(r"\s+", " ", safe_arg_str).strip()

    cartella_suggerita = f"[{date_val}] {materia_val.upper()} - {safe_arg_str}"

    res = {
        "valid": True,
        "data": date_val,
        "materia": materia_val.upper(),
        "titolo": titolo_val if titolo_val else None,
        "argomenti": argomenti_list,
        "cartella_suggerita": cartella_suggerita
    }

    print(json.dumps(res, ensure_ascii=False, indent=2))
    sys.exit(0)

def extract(pre_path, dest_dir):
    if not os.path.exists(pre_path):
        print(f"Errore: {pre_path} non trovato.", file=sys.stderr)
        sys.exit(1)

    os.makedirs(dest_dir, exist_ok=True)

    with open(pre_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    ambiguities = []
    errors = []

    # Regex per catturare: codice (AMB1), timecode, e opzionale ASR originale | ASR: "testo"
    amb_pattern = re.compile(rf"(?:⚠️|⚠)\s*(AMB\d+)\s*({TIMECODE_REGEX})(?:\s*\|\s*ASR:\s*\"?([^\")]+)\"?)?")
    err_pattern = re.compile(rf"(?:⁉️|⁉)\s*(ERR\d+)\s*({TIMECODE_REGEX})")

    for line in lines:
        clean_l = line.strip()
        if not clean_l:
            continue

        for match in amb_pattern.finditer(line):
            code = match.group(1)
            timecode = match.group(2)
            asr_orig = match.group(3) if match.group(3) else "Non specificato"
            focal_ctx = extract_focal_context(line, match.start(), match.end())
            ambiguities.append((timecode, code, asr_orig.strip(), focal_ctx))

        for match in err_pattern.finditer(line):
            code = match.group(1)
            timecode = match.group(2)
            focal_ctx = extract_focal_context(line, match.start(), match.end(), max_words_before=20, max_words_after=20)
            errors.append((timecode, code, focal_ctx))

    # 1. Scrittura Revisioni ASR.md con formato dettagliato e contesto focalizzato
    asr_path = os.path.join(dest_dir, "Revisioni ASR.md")
    with open(asr_path, "w", encoding="utf-8") as f:
        f.write("# Revisioni ASR (Ambiguità di Trascrizione)\n\n")
        if ambiguities:
            for tc, code, asr_orig, ctx in ambiguities:
                f.write(f"- **{tc}** ({code}):\n")
                f.write(f"  - **ASR originale**: \"{asr_orig}\"\n")
                f.write(f"  - **Testo adottato**: {ctx}\n\n")
        else:
            f.write("_Nessuna ambiguità critica rilevata nel trascritto._\n")

    # 2. Scrittura Errori concettuali.md con formato chiaro per la revisione
    err_path = os.path.join(dest_dir, "Errori concettuali.md")
    with open(err_path, "w", encoding="utf-8") as f:
        if errors:
            f.write("# Errori Concettuali Rilevati\n\n")
            for tc, code, ctx in errors:
                f.write(f"- **{tc}** ({code}):\n")
                f.write(f"  - **Passo del docente**: \"{ctx}\"\n\n")
        else:
            # File creato e vuoto se non ci sono errori
            pass

    print(f"Estratti con successo: {len(ambiguities)} ambiguità ASR, {len(errors)} errori concettuali.")

def clean(pre_path, out_path):
    if not os.path.exists(pre_path):
        print(f"Errore: {pre_path} non trovato.", file=sys.stderr)
        sys.exit(1)

    with open(pre_path, "r", encoding="utf-8") as f:
        content = f.read()

    cleaned = re.sub(rf"\s*\(\s*(?:⁉️|⚠️|⁉|⚠)\s*(?:AMB|ERR)\d+\s*{TIMECODE_REGEX}.*?\)", "", content)
    cleaned = re.sub(rf"\s*(?:⁉️|⚠️|⁉|⚠)\s*(?:AMB|ERR)\d+\s*{TIMECODE_REGEX}.*?(?=\s|$)", "", cleaned)
    cleaned = re.sub(r"\(\s*\)", "", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(cleaned)

    print(f"File ripulito generato in: {out_path}")

def merge_parts(directory, out_path=None):
    if out_path is None:
        out_path = os.path.join(directory, "pre-elaborato.md")

    if not os.path.isdir(directory):
        print(f"Errore: cartella '{directory}' non trovata.", file=sys.stderr)
        sys.exit(1)

    part_files = sorted([
        f for f in os.listdir(directory)
        if f.startswith("_part_") and f.endswith(".md")
    ])
    if not part_files:
        print(f"Errore: nessun file _part_*.md trovato in {directory}", file=sys.stderr)
        sys.exit(1)

    parts = [os.path.join(directory, f) for f in part_files]

    with open(out_path, "w", encoding="utf-8") as outfile:
        for i, p in enumerate(parts):
            with open(p, "r", encoding="utf-8") as infile:
                content = infile.read().strip()
                if content:
                    outfile.write(content)
                    outfile.write("\n\n")
            try:
                os.remove(p)
            except OSError as e:
                print(f"Avviso: impossibile rimuovere {p}: {e}", file=sys.stderr)

    print(f"Uniti {len(parts)} file di sezione con successo in: {out_path}")

def append_part(target_path, source_input):
    if os.path.exists(source_input):
        with open(source_input, "r", encoding="utf-8") as sf:
            text_to_append = sf.read().strip()
        try:
            os.remove(source_input)
        except OSError:
            pass
    else:
        text_to_append = source_input.strip()

    with open(target_path, "a", encoding="utf-8") as tf:
        tf.write("\n\n" + text_to_append + "\n")
    print(f"Sezione appesa con successo a: {target_path}")

def _format_yaml_value(value):
    """Formatta un valore per YAML, aggiungendo apici singoli se necessario."""
    s = str(value)
    if not s:
        return "''"
    if re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', s):
        return s
    escaped = s.replace("'", "''")
    return f"'{escaped}'"

def update_info(yaml_path, updates_dict):
    """Aggiorna campi in info.yaml preservando struttura, ordine e commenti."""
    if not os.path.exists(yaml_path):
        print(f"Errore: {yaml_path} non trovato.", file=sys.stderr)
        sys.exit(1)

    with open(yaml_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    updated_keys = set()
    new_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped and ':' in stripped and not stripped.startswith('#') and not stripped.startswith('-'):
            key = stripped.split(':', 1)[0].strip()
            if key in updates_dict:
                value = updates_dict[key]
                formatted = _format_yaml_value(value)
                new_lines.append(f"{key}: {formatted}\n")
                updated_keys.add(key)
                continue
        new_lines.append(line)

    for key, value in updates_dict.items():
        if key not in updated_keys:
            formatted = _format_yaml_value(value)
            new_lines.append(f"{key}: {formatted}\n")

    with open(yaml_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    summary = ", ".join(f"{k}={v}" for k, v in updates_dict.items())
    print(f"info.yaml aggiornato: {summary}")

def _read_info_yaml(yaml_path):
    """Legge info.yaml e restituisce un dizionario con i campi."""
    data = {}
    with open(yaml_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('-'):
                continue
            if ':' in line:
                k, v = line.split(':', 1)
                data[k.strip()] = v.strip().strip("\"'")
    return data

def _read_frontmatter(md_path):
    """Legge il frontmatter YAML da un file markdown e restituisce un dizionario."""
    with open(md_path, "r", encoding="utf-8") as f:
        header_sample = "".join(f.readline() for _ in range(50))

    match = re.match(r"^\s*---\s*\n([\s\S]*?)\n---", header_sample)
    if not match:
        return {}

    yaml_block = match.group(1)
    data = {}
    try:
        import yaml
        parsed = yaml.safe_load(yaml_block)
        if isinstance(parsed, dict):
            data = parsed
    except Exception:
        for line in yaml_block.splitlines():
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('-'):
                continue
            if ':' in line:
                k, v = line.split(':', 1)
                data[k.strip().lower()] = v.strip().strip("\"'")
    return data

def init_project(directory):
    """Valida la cartella rt-setup, restituisce i metadati e aggiorna lo stato."""
    if not os.path.isdir(directory):
        print(f"Errore: cartella '{directory}' non trovata.", file=sys.stderr)
        sys.exit(1)

    yaml_path = os.path.join(directory, "info.yaml")
    trascritto_path = os.path.join(directory, "trascritto grezzo.md")

    # Verifica file critici
    missing_critical = []
    if not os.path.exists(yaml_path):
        missing_critical.append("info.yaml")
    if not os.path.exists(trascritto_path):
        missing_critical.append("trascritto grezzo.md")
    if missing_critical:
        print(f"Errore: file critici mancanti: {', '.join(missing_critical)}", file=sys.stderr)
        sys.exit(1)

    # Nessun placeholder prematuro creato (verranno generati dalle fasi di build/pipeline)
    created = []

    # Leggi metadati
    info = _read_info_yaml(yaml_path)
    data_val = info.get("data", "")
    materia_val = info.get("materia", "")
    argomenti_val = info.get("argomenti", "")
    fase = info.get("fase_corrente", "sconosciuta")

    # Aggiorna stato
    update_info(yaml_path, {"fase_corrente": "fase_2_rielaborazione", "stato": "in_corso"})

    # Output JSON compatto per l'LLM
    result = {
        "status": "ready",
        "data": data_val,
        "materia": materia_val,
        "argomenti": argomenti_val,
        "fase_precedente": fase,
        "placeholder_creati": created,
        "trascritto": trascritto_path
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))

def rename_final(directory):
    """Rinomina il file rielaborato e la cartella con il titolo accademico dal frontmatter."""
    if not os.path.isdir(directory):
        print(f"Errore: cartella '{directory}' non trovata.", file=sys.stderr)
        sys.exit(1)

    pre_path = os.path.join(directory, "pre-elaborato.md")
    rielaborato_path = os.path.join(directory, "rielaborato.md")
    yaml_path = os.path.join(directory, "info.yaml")

    if not os.path.exists(pre_path):
        print(f"Errore: {pre_path} non trovato.", file=sys.stderr)
        sys.exit(1)

    # Leggi titolo, materia, data dal frontmatter di pre-elaborato.md
    fm = _read_frontmatter(pre_path)
    titolo = str(fm.get("titolo", "")).strip()
    materia = str(fm.get("materia", "")).strip()
    data_val = str(fm.get("data", "")).strip()

    # Fallback: leggi da info.yaml se mancano nel frontmatter
    if not materia or not data_val:
        info = _read_info_yaml(yaml_path)
        if not materia:
            materia = info.get("materia", "MATERIA")
        if not data_val:
            data_val = info.get("data", "0000-00-00")

    if not titolo:
        print("Errore: campo 'titolo' non trovato nel frontmatter di pre-elaborato.md.", file=sys.stderr)
        sys.exit(1)

    # Sanitizza il titolo per il filesystem
    safe_titolo = re.sub(r'[/\\:*?"<>|]', ' ', titolo)
    safe_titolo = re.sub(r'\s+', ' ', safe_titolo).strip()

    nome_finale = f"[{data_val}] {materia.upper()} - {safe_titolo}"

    # Tronca se il nome supera il limite del filesystem (255 byte su macOS)
    # Riserva spazio per l'estensione ".md" (3 byte) nel caso del file
    max_bytes = 251
    while len(nome_finale.encode("utf-8")) > max_bytes:
        # Tronca all'ultima virgola o spazio per non tagliare parole
        cut = nome_finale.rfind(",", 0, len(nome_finale) - 1)
        if cut <= 0:
            cut = nome_finale.rfind(" ", 0, len(nome_finale) - 1)
        if cut <= 0:
            nome_finale = nome_finale[:max_bytes]
            break
        nome_finale = nome_finale[:cut].rstrip()

    # 1. Rinomina rielaborato.md
    new_file_path = os.path.join(directory, nome_finale + ".md")
    if os.path.exists(rielaborato_path):
        os.rename(rielaborato_path, new_file_path)
        print(f"File rinominato: rielaborato.md → {nome_finale}.md")
    else:
        print(f"Avviso: rielaborato.md non trovato, salto rinomina file.", file=sys.stderr)

    # 2. Rinomina cartella
    parent_dir = os.path.dirname(os.path.abspath(directory))
    new_dir_path = os.path.join(parent_dir, nome_finale)
    old_dir_path = os.path.abspath(directory)

    if old_dir_path != new_dir_path:
        if os.path.exists(new_dir_path):
            print(f"Avviso: cartella destinazione '{nome_finale}' esiste già, salto rinomina cartella.", file=sys.stderr)
        else:
            os.rename(old_dir_path, new_dir_path)
            print(f"Cartella rinominata: {os.path.basename(old_dir_path)} → {nome_finale}")
    else:
        print(f"Cartella già nominata correttamente: {nome_finale}")

    # 3. Aggiorna info.yaml (nel nuovo percorso)
    new_yaml_path = os.path.join(new_dir_path if old_dir_path != new_dir_path else directory, "info.yaml")
    if os.path.exists(new_yaml_path):
        update_info(new_yaml_path, {
            "fase_corrente": "completato",
            "stato": "completato",
            "titolo": titolo,
            "cartella": nome_finale
        })

    result = {
        "status": "renamed",
        "nome_finale": nome_finale,
        "file": nome_finale + ".md",
        "cartella": new_dir_path if old_dir_path != new_dir_path else old_dir_path
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso:")
        print("  python3 process_markers.py init        <cartella>")
        print("  python3 process_markers.py check-yaml  <file_trascritto>")
        print("  python3 process_markers.py merge       <cartella> [output_file]")
        print("  python3 process_markers.py append      <target_file> <source_file_o_testo>")
        print("  python3 process_markers.py extract     <pre-elaborato.md> <cartella_dest>")
        print("  python3 process_markers.py clean       <pre-elaborato.md> <output_pulito.md>")
        print("  python3 process_markers.py rename      <cartella>")
        print("  python3 process_markers.py update-info <info.yaml> chiave1=valore1 [chiave2=valore2 ...]")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "init":
        if len(sys.argv) < 3:
            print("Uso: python3 process_markers.py init <cartella>", file=sys.stderr)
            sys.exit(1)
        init_project(sys.argv[2])
    elif cmd == "check-yaml":
        if len(sys.argv) < 3:
            print("Uso: python3 process_markers.py check-yaml <file_trascritto>", file=sys.stderr)
            sys.exit(1)
        check_yaml(sys.argv[2])
    elif cmd == "merge":
        if len(sys.argv) < 3:
            print("Uso: python3 process_markers.py merge <cartella> [output_file]", file=sys.stderr)
            sys.exit(1)
        dest_file = sys.argv[3] if len(sys.argv) > 3 else None
        merge_parts(sys.argv[2], dest_file)
    elif cmd == "append":
        if len(sys.argv) < 4:
            print("Uso: python3 process_markers.py append <target_file> <source_file_o_testo>", file=sys.stderr)
            sys.exit(1)
        append_part(sys.argv[2], sys.argv[3])
    elif cmd == "extract":
        if len(sys.argv) < 4:
            print("Uso: python3 process_markers.py extract <pre-elaborato.md> <cartella_dest>", file=sys.stderr)
            sys.exit(1)
        extract(sys.argv[2], sys.argv[3])
    elif cmd == "clean":
        if len(sys.argv) < 4:
            print("Uso: python3 process_markers.py clean <pre-elaborato.md> <output_pulito.md>", file=sys.stderr)
            sys.exit(1)
        clean(sys.argv[2], sys.argv[3])
    elif cmd == "rename":
        if len(sys.argv) < 3:
            print("Uso: python3 process_markers.py rename <cartella>", file=sys.stderr)
            sys.exit(1)
        rename_final(sys.argv[2])
    elif cmd == "update-info":
        if len(sys.argv) < 4:
            print("Uso: python3 process_markers.py update-info <info.yaml> chiave1=valore1 [chiave2=valore2 ...]", file=sys.stderr)
            sys.exit(1)
        yaml_path = sys.argv[2]
        updates = {}
        for arg in sys.argv[3:]:
            if '=' not in arg:
                print(f"Errore: formato non valido '{arg}', atteso chiave=valore", file=sys.stderr)
                sys.exit(1)
            k, v = arg.split('=', 1)
            updates[k.strip()] = v.strip()
        update_info(yaml_path, updates)
    else:
        print(f"Comando sconosciuto: {cmd}", file=sys.stderr)
        sys.exit(1)

