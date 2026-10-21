"""Test per rt.core.bundle: lettura build_info e formattazione riga di build."""
import json
from rt.core import bundle


def test_build_info_missing_file_returns_empty(tmp_path):
    assert bundle.build_info(str(tmp_path)) == {}


def test_build_info_corrupted_file_returns_empty(tmp_path):
    (tmp_path / bundle.BUILD_INFO_FILE).write_text("non json valido {", encoding="utf-8")
    assert bundle.build_info(str(tmp_path)) == {}


def test_build_info_valid_file_returns_dict(tmp_path):
    data = {
        "version": "4.3.2b1",
        "commit": "a1b2c3d",
        "built_at": "2026-10-19T14:30:00Z",
        "run": "812",
        "target": "macos",
    }
    (tmp_path / bundle.BUILD_INFO_FILE).write_text(json.dumps(data), encoding="utf-8")
    assert bundle.build_info(str(tmp_path)) == data


def test_format_build_formats_all_parts():
    info = {
        "version": "4.3.2b1",
        "commit": "a1b2c3d",
        "built_at": "2026-10-19T14:30:00Z",
        "run": "812",
        "target": "macos",
    }
    assert bundle.format_build(info) == "build 812 · a1b2c3d · 19/10/2026"


def test_format_build_empty_returns_none():
    assert bundle.format_build({}) is None


def test_format_build_partial_fields():
    assert bundle.format_build({"commit": "a1b2c3d"}) == "a1b2c3d"
    assert bundle.format_build({"run": "812", "commit": "a1b2c3d"}) == "build 812 · a1b2c3d"
    assert bundle.format_build({"built_at": "2026-10-19T14:30:00Z"}) == "19/10/2026"
