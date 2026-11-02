import logging


def test_multipart_upload_logs_duration_and_size(api_client, caplog):
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        api_client.post("/api/v1/archive/inspect", files={"file": ("slide.pdf", b"x" * 2_000_000, "application/pdf")})
        api_client.get("/api/v1/health")
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Upload ")]
    assert len(lines) == 1
    assert lines[0].startswith("Upload POST /api/v1/archive/inspect: ")
    assert " s, 2.0 MB, stato " in lines[0]
