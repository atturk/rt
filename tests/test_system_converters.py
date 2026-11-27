"""Test per disponibilità convertitori di presentazioni (.pptx -> immagini)."""
from unittest.mock import patch

from rt.core import materials


def test_available_slide_methods_excludes_quicklook():
    with (
        patch("rt.core.materials._soffice", return_value=None),
        patch("rt.core.materials._has_powerpoint", return_value=False),
        patch("rt.core.materials._has_keynote", return_value=False),
        patch("shutil.which", return_value="/usr/bin/qlmanage"),
    ):
        assert materials.available_slide_methods() == []


def test_available_slide_methods_collects_reliable_tools():
    with (
        patch("rt.core.materials._soffice", return_value="/usr/bin/soffice"),
        patch("rt.core.materials._has_powerpoint", return_value=False),
        patch("rt.core.materials._has_keynote", return_value=True),
    ):
        assert materials.available_slide_methods() == ["LibreOffice", "Keynote"]


def test_system_converters_endpoint_available_and_missing(api_client):
    with (
        patch("rt.core.materials.available_slide_methods", return_value=[]),
        patch("rt.core.materials.has_quicklook", return_value=True),
    ):
        res = api_client.get("/api/v1/system/converters")
        assert res.status_code == 200
        body = res.json()
        assert body["pptx"]["available"] is False
        assert body["pptx"]["methods"] == []
        assert body["pptx"]["quicklook_available"] is True
        assert isinstance(body["pptx"]["platform"], str)

    with (
        patch("rt.core.materials.available_slide_methods", return_value=["LibreOffice", "PowerPoint"]),
        patch("rt.core.materials.has_quicklook", return_value=False),
    ):
        res = api_client.get("/api/v1/system/converters")
        assert res.status_code == 200
        body = res.json()
        assert body["pptx"]["available"] is True
        assert body["pptx"]["methods"] == ["LibreOffice", "PowerPoint"]
        assert body["pptx"]["quicklook_available"] is False
