"""Servizio di alleggerimento audio delle lezioni (AU2d)."""
import json
import os
from rt.core.lesson_paths import lesson_path
from rt.core.sources import load_sources, _save, compute_file_sha256
from rt.pipeline.setup import transcode_audio_for_storage
from rt.services.lesson_service import known_lesson_dirs, lessons_root
from rt.storage import fs


def all_lessons_list(explicit_dirs=None):
    if explicit_dirs:
        return explicit_dirs
    dirs = set(known_lesson_dirs())
    root = lessons_root()
    if fs.isdir(root):
        for entry in fs.listdir(root):
            full = os.path.join(root, entry)
            if fs.isdir(full) and fs.isfile(os.path.join(full, "info.yaml")):
                dirs.add(full)
    return sorted(dirs)


def _history_dirs(ldir):
    history_dir = os.path.join(ldir, "history")
    if not fs.isdir(history_dir):
        return []
    return [os.path.join(history_dir, v) for v in fs.listdir(history_dir)
            if fs.isdir(os.path.join(history_dir, v))]


def referenced_audio_files(ldir):
    """File indicati dalla lezione o da una sua fotografia (Annulla, Versioni): mai orfani."""
    from rt.core.state import read_info_yaml
    referenced = {os.path.normpath(s.file) for s in load_sources(ldir, include_removed=True)}
    for folder in [ldir, *_history_dirs(ldir)]:
        info_path = os.path.join(folder, "info.yaml")
        if fs.isfile(info_path):
            try:
                fa = read_info_yaml(info_path).get("file_audio")
            except Exception:
                fa = None
            if fa:
                referenced.add(os.path.normpath(fa))
        if folder != ldir:
            v_sources_path = os.path.join(folder, "sources.json")
            if fs.isfile(v_sources_path):
                try:
                    with fs.open(v_sources_path, encoding="utf-8") as stream:
                        referenced.update(os.path.normpath(item["file"]) for item in json.load(stream)
                                          if item.get("file"))
                except Exception:
                    pass
    return referenced


def preview_compact_audio(lesson_dirs=None):
    dirs = all_lessons_list(lesson_dirs)
    file_convertibili = 0
    bytes_convertibili = 0
    file_orfani = 0
    bytes_orfani = 0

    for ldir in dirs:
        sources = load_sources(ldir, include_removed=True)
        referenced_files = set()
        counted_convertible = set()
        for s in sources:
            norm_rel = os.path.normpath(s.file)
            referenced_files.add(norm_rel)
            ext = os.path.splitext(s.file)[1].lower()
            if s.tipo == "audio" and ext in (".wav", ".flac"):
                path = os.path.join(ldir, s.file)
                if fs.isfile(path) and norm_rel not in counted_convertible:
                    counted_convertible.add(norm_rel)
                    file_convertibili += 1
                    bytes_convertibili += fs.getsize(path)

        # Controlla anche fonti nelle versioni storiche
        history_dir = os.path.join(ldir, "history")
        if fs.isdir(history_dir):
            for v in fs.listdir(history_dir):
                v_sources_path = os.path.join(history_dir, v, "sources.json")
                if fs.isfile(v_sources_path):
                    try:
                        with fs.open(v_sources_path, encoding="utf-8") as stream:
                            raw = json.load(stream)
                            for item in raw:
                                rel = item.get("file")
                                if rel:
                                    norm_rel = os.path.normpath(rel)
                                    referenced_files.add(norm_rel)
                                    if item.get("tipo") == "audio" and os.path.splitext(rel)[1].lower() in (".wav", ".flac"):
                                        p = os.path.join(ldir, rel)
                                        if fs.isfile(p) and norm_rel not in counted_convertible:
                                            counted_convertible.add(norm_rel)
                                            file_convertibili += 1
                                            bytes_convertibili += fs.getsize(p)
                    except Exception:
                        pass

        referenced = referenced_audio_files(ldir)
        for cand in _orphan_candidates(ldir):
            if os.path.normpath(cand) not in referenced:
                p = os.path.join(ldir, cand)
                if fs.isfile(p):
                    file_orfani += 1
                    bytes_orfani += fs.getsize(p)

    spazio_stimato = bytes_orfani + int(bytes_convertibili * 0.85)
    return {
        "file_convertibili": file_convertibili,
        "bytes_convertibili": bytes_convertibili,
        "file_orfani": file_orfani,
        "bytes_orfani": bytes_orfani,
        "spazio_stimato_liberato": spazio_stimato,
    }


def _orphan_candidates(ldir):
    candidates = [name for name in fs.listdir(ldir)
                  if (name.startswith("audio-") or name == "audio completo.m4a") and name.endswith(".m4a")]
    sources_dir = os.path.join(ldir, "sources")
    if fs.isdir(sources_dir):
        for sub in fs.listdir(sources_dir):
            sub_path = os.path.join(sources_dir, sub)
            if fs.isdir(sub_path):
                candidates.extend(os.path.join("sources", sub, name) for name in fs.listdir(sub_path)
                                  if (name.startswith("audio-") or name == "audio completo.m4a")
                                  and name.endswith(".m4a"))
    return candidates


def _convert(ldir, rel):
    """(nuovo percorso relativo, impronta, byte liberati) oppure None se ffmpeg non riesce."""
    path = os.path.join(ldir, rel)
    old_size = fs.getsize(path)
    new_rel = os.path.splitext(rel)[0] + ".m4a"
    new_path = os.path.join(ldir, new_rel)
    with fs.materialize(path) as mat_in, fs.external_output(new_path) as ext_out:
        ok = transcode_audio_for_storage(mat_in, ext_out)
    if not ok:
        return None
    freed = max(0, old_size - fs.getsize(new_path))
    fs.remove(path)
    return new_rel, compute_file_sha256(new_path), freed


def _compact_lesson(ldir):
    from rt.core.state import read_info_yaml, update_info_yaml
    converted = {}  # vecchio percorso -> (nuovo, impronta)
    freed = 0
    sources = load_sources(ldir, include_removed=True)
    history_registries = []
    for folder in _history_dirs(ldir):
        v_sources_path = os.path.join(folder, "sources.json")
        if fs.isfile(v_sources_path):
            try:
                with fs.open(v_sources_path, encoding="utf-8") as stream:
                    history_registries.append((v_sources_path, json.load(stream)))
            except Exception:
                pass
    # Ogni wav/flac (corrente, tolto o solo nelle fotografie) si converte una volta sola;
    # poi registro, fotografie e info.yaml si riallineano dalla stessa mappa.
    wanted = [s.file for s in sources if s.tipo == "audio"]
    wanted += [item.get("file") for _, raw in history_registries for item in raw
               if item.get("tipo") == "audio" and item.get("file")]
    for rel in dict.fromkeys(wanted):
        if os.path.splitext(rel)[1].lower() in (".wav", ".flac") and fs.isfile(os.path.join(ldir, rel)):
            result = _convert(ldir, rel)
            if result:
                converted[rel] = result[:2]
                freed += result[2]
    if converted:
        for s in sources:
            if s.file in converted:
                s.file, s.impronta = converted[s.file]
        _save(ldir, sources)
        for v_sources_path, raw in history_registries:
            changed = False
            for item in raw:
                if item.get("file") in converted:
                    item["file"], item["impronta"] = converted[item["file"]]
                    changed = True
            if changed:
                with fs.open(v_sources_path + ".tmp", "w", encoding="utf-8") as stream:
                    json.dump(raw, stream, ensure_ascii=False, indent=2)
                fs.replace(v_sources_path + ".tmp", v_sources_path)
        for folder in [ldir, *_history_dirs(ldir)]:
            info_path = os.path.join(folder, "info.yaml")
            if fs.isfile(info_path) and read_info_yaml(info_path).get("file_audio") in converted:
                update_info_yaml(info_path, {"file_audio": converted[read_info_yaml(info_path)["file_audio"]][0]})
    referenced = referenced_audio_files(ldir)
    removed = 0
    for cand in _orphan_candidates(ldir):
        if os.path.normpath(cand) not in referenced:
            p = os.path.join(ldir, cand)
            if fs.isfile(p):
                freed += fs.getsize(p)
                fs.remove(p)
                removed += 1
    return len(converted), removed, freed


def compact_audio_lessons(lesson_dirs=None, ctx=None):
    from rt.core.lesson_lock import lesson_lock
    file_convertiti = 0
    file_orfani_cancellati = 0
    bytes_liberati = 0
    for ldir in all_lessons_list(lesson_dirs):
        if ctx:
            ctx.check_cancelled()
        # Sotto il lock della lezione: una preparazione in corso non perde il suo audio.
        with lesson_lock(ldir):
            converted, removed, freed = _compact_lesson(ldir)
        file_convertiti += converted
        file_orfani_cancellati += removed
        bytes_liberati += freed
    return {
        "file_convertiti": file_convertiti,
        "file_orfani_cancellati": file_orfani_cancellati,
        "bytes_liberati": bytes_liberati,
    }
