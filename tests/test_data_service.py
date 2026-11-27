

def test_new_config_falls_back_to_macparakeet_without_onnx(tmp_path, monkeypatch):
    from rt.core import onnx_stt
    from rt.services import data_service
    monkeypatch.setattr(onnx_stt, "available", lambda: False)
    target = data_service.init_data_dir(str(tmp_path / "dati"), say=lambda _m: None)
    text = (tmp_path / "dati" / "config" / "general.yaml").read_text(encoding="utf-8")
    assert 'engine: "macparakeet"' in text
    monkeypatch.setattr(onnx_stt, "available", lambda: True)
    monkeypatch.setattr("sys.platform", "linux")
    data_service.init_data_dir(str(tmp_path / "altri"), say=lambda _m: None)
    assert 'engine: "parakeet"' in (tmp_path / "altri" / "config" / "general.yaml").read_text(encoding="utf-8")
    monkeypatch.setattr("sys.platform", "darwin")
    data_service.init_data_dir(str(tmp_path / "mac"), say=lambda _m: None)
    assert 'engine: "macparakeet"' in (tmp_path / "mac" / "config" / "general.yaml").read_text(encoding="utf-8")
    assert target
