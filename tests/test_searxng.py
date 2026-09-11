import pytest
from unittest.mock import MagicMock, patch
from rt.core.searxng_client import search_images, download_image, WebImageResult


def test_search_images_success(monkeypatch):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "results": [
            {"img_src": "http://example.com/img1.png", "title": "Image 1", "url": "http://example.com/page1"},
            {"url": "http://example.com/img2.jpg", "title": "Image 2"},
            {"title": "No image url"},
        ]
    }

    def mock_get(url, params=None, timeout=None):
        return mock_resp

    monkeypatch.setattr("requests.get", mock_get)

    res = search_images("http://localhost:8080", "trigliceridi", count=5)
    assert len(res) == 2
    assert res[0].image_url == "http://example.com/img1.png"
    assert res[0].title == "Image 1"
    assert res[1].image_url == "http://example.com/img2.jpg"


def test_search_images_errors(monkeypatch):
    mock_resp = MagicMock()
    mock_resp.status_code = 500

    def mock_get(url, params=None, timeout=None):
        return mock_resp

    monkeypatch.setattr("requests.get", mock_get)

    with pytest.raises(ValueError) as exc_info:
        search_images("http://localhost:8080", "query")
    assert "status 500" in str(exc_info.value)


def test_download_image_success(monkeypatch):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b"fake bytes"

    def mock_get(url, timeout=None):
        return mock_resp

    monkeypatch.setattr("requests.get", mock_get)

    data = download_image("http://example.com/image.png")
    assert data == b"fake bytes"


def test_download_image_error(monkeypatch):
    mock_resp = MagicMock()
    mock_resp.status_code = 404

    def mock_get(url, timeout=None):
        return mock_resp

    monkeypatch.setattr("requests.get", mock_get)

    with pytest.raises(ValueError):
        download_image("http://example.com/404.png")
