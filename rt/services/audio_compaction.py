"""Servizio di alleggerimento audio delle lezioni (AU2d)."""
import json
import os
from rt.core.lesson_paths import lesson_path
from rt.core.sources import load_sources, _save, compute_file_sha256
from rt.pipeline.setup import transcode_audio_for_storage
from rt.pipeline.source_update import _read_state, _write_state
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


def preview_compact_audio(lesson_dirs=None):
    dirs = all_lessons_list(lesson_dirs)
    file_convertibili = 0
    bytes_convertibili = 0
    file_orfani = 0
    bytes_orfani = 0

    for ldir in dirs:
        sources = load_sources(ldir)
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

        # Audio file in info.yaml
        info_path = lesson_path(ldir, "info.yaml")
        if fs.isfile(info_path):
            from rt.core.state import read_info_yaml
            fa = read_info_yaml(info_path).get("file_audio")
            if fa:
                referenced_files.add(os.path.normpath(fa))

        # Cerca audio orfani uniti (es. audio-*.m4a, audio completo.m4a)
        candidates = []
        for name in fs.listdir(ldir):
            if (name.startswith("audio-") or name == "audio completo.m4a") and name.endswith(".m4a"):
                candidates.append(name)
        sources_dir = os.path.join(ldir, "sources")
        if fs.isdir(sources_dir):
            for sub in fs.listdir(sources_dir):
                sub_path = os.path.join(sources_dir, sub)
                if fs.isdir(sub_path):
                    for name in fs.listdir(sub_path):
                        if (name.startswith("audio-") or name == "audio completo.m4a") and name.endswith(".m4a"):
                            candidates.append(os.path.join("sources", sub, name))

        for cand in candidates:
            if os.path.normpath(cand) not in referenced_files:
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


def compact_audio_lessons(lesson_dirs=None, ctx=None):
    dirs = all_lessons_list(lesson_dirs)
    file_convertiti = 0
    file_orfani_cancellati = 0
    bytes_liberati = 0

    for ldir in dirs:
        if ctx:
            ctx.check_cancelled()
        sources = load_sources(ldir)
        state = _read_state(ldir)
        sources_modified = False

        # Converti wav/flac nelle fonti correnti
        for s in sources:
            ext = os.path.splitext(s.file)[1].lower()
            if s.tipo == "audio" and ext in (".wav", ".flac"):
                path = os.path.join(ldir, s.file)
                if fs.isfile(path):
                    old_rel = s.file
                    old_size = fs.getsize(path)
                    new_rel = os.path.splitext(s.file)[0] + ".m4a"
                    new_path = os.path.join(ldir, new_rel)
                    with fs.materialize(path) as mat_in, fs.external_output(new_path) as ext_out:
                        ok = transcode_audio_for_storage(mat_in, ext_out)
                    if ok:
                        new_size = fs.getsize(new_path)
                        fs.remove(path)
                        bytes_liberati += max(0, old_size - new_size)
                        s.file = new_rel
                        s.impronta = compute_file_sha256(new_path)
                        sources_modified = True
                        file_convertiti += 1
                        info_path = lesson_path(ldir, "info.yaml")
                        if fs.isfile(info_path):
                            from rt.core.state import read_info_yaml, update_info_yaml
                            if read_info_yaml(info_path).get("file_audio") == old_rel:
                                update_info_yaml(info_path, {"file_audio": new_rel})
                        if "sources" in state and s.id in state["sources"]:
                            state["sources"][s.id]["fingerprint"] = s.impronta
                            state["sources"][s.id]["impronta"] = s.impronta

        if sources_modified:
            _save(ldir, sources)
            _write_state(ldir, state)

        # Converti anche wav/flac nelle versioni storiche (fonti tolte)
        history_dir = os.path.join(ldir, "history")
        if fs.isdir(history_dir):
            for v in fs.listdir(history_dir):
                v_sources_path = os.path.join(history_dir, v, "sources.json")
                if fs.isfile(v_sources_path):
                    try:
                        with fs.open(v_sources_path, "r", encoding="utf-8") as stream:
                            raw = json.load(stream)
                        v_modified = False
                        for item in raw:
                            rel = item.get("file")
                            if rel and item.get("tipo") == "audio" and os.path.splitext(rel)[1].lower() in (".wav", ".flac"):
                                p = os.path.join(ldir, rel)
                                if fs.isfile(p):
                                    old_rel = rel
                                    old_size = fs.getsize(p)
                                    new_rel = os.path.splitext(rel)[0] + ".m4a"
                                    new_p = os.path.join(ldir, new_rel)
                                    with fs.materialize(p) as mat_in, fs.external_output(new_p) as ext_out:
                                        ok = transcode_audio_for_storage(mat_in, ext_out)
                                    if ok:
                                        new_size = fs.getsize(new_p)
                                        fs.remove(p)
                                        bytes_liberati += max(0, old_size - new_size)
                                        item["file"] = new_rel
                                        item["impronta"] = compute_file_sha256(new_p)
                                        v_modified = True
                                        file_convertiti += 1
                                        v_info_path = os.path.join(history_dir, v, "info.yaml")
                                        if fs.isfile(v_info_path):
                                            from rt.core.state import read_info_yaml, update_info_yaml
                                            if read_info_yaml(v_info_path).get("file_audio") == old_rel:
                                                update_info_yaml(v_info_path, {"file_audio": new_rel})
                                        if "sources" in state and item.get("id") in state["sources"]:
                                            state["sources"][item["id"]]["fingerprint"] = item["impronta"]
                                            state["sources"][item["id"]]["impronta"] = item["impronta"]
                        if v_modified:
                            with fs.open(v_sources_path + ".tmp", "w", encoding="utf-8") as stream:
                                json.dump(raw, stream, ensure_ascii=False, indent=2)
                            fs.replace(v_sources_path + ".tmp", v_sources_path)
                            _write_state(ldir, state)
                    except Exception:
                        pass

        # Cancella audio uniti orfani
        referenced = set()
        for s in load_sources(ldir):
            referenced.add(os.path.normpath(s.file))
        info_path = lesson_path(ldir, "info.yaml")
        if fs.isfile(info_path):
            from rt.core.state import read_info_yaml
            fa = read_info_yaml(info_path).get("file_audio")
            if fa:
                referenced.add(os.path.normpath(fa))
        if fs.isdir(history_dir):
            for v in fs.listdir(history_dir):
                v_sources_path = os.path.join(history_dir, v, "sources.json")
                if fs.isfile(v_sources_path):
                    try:
                        with fs.open(v_sources_path, "r", encoding="utf-8") as stream:
                            for item in json.load(stream):
                                if item.get("file"):
                                    referenced.add(os.path.normpath(item["file"]))
                    except Exception:
                        pass

        candidates = []
        for name in fs.listdir(ldir):
            if (name.startswith("audio-") or name == "audio completo.m4a") and name.endswith(".m4a"):
                candidates.append(name)
        sources_dir = os.path.join(ldir, "sources")
        if fs.isdir(sources_dir):
            for sub in fs.listdir(sources_dir):
                sub_path = os.path.join(sources_dir, sub)
                if fs.isdir(sub_path):
                    for name in fs.listdir(sub_path):
                        if (name.startswith("audio-") or name == "audio completo.m4a") and name.endswith(".m4a"):
                            candidates.append(os.path.join("sources", sub, name))

        for cand in candidates:
            if os.path.normpath(cand) not in referenced:
                p = os.path.join(ldir, cand)
                if fs.isfile(p):
                    sz = fs.getsize(p)
                    fs.remove(p)
                    file_orfani_cancellati += 1
                    bytes_liberati += sz

    return {
        "file_convertiti": file_convertiti,
        "file_orfani_cancellati": file_orfani_cancellati,
        "bytes_liberati": bytes_liberati,
    }
