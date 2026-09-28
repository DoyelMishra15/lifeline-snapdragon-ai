import sys, os

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from lib import s3_store


def test_rejects_disallowed_content_type():
    ok, msg = s3_store.validate_upload_request("application/x-msdownload", 1000)
    assert ok is False
    assert "Unsupported" in msg


def test_accepts_allowed_content_type():
    ok, msg = s3_store.validate_upload_request("application/pdf", 1000)
    assert ok is True
    assert msg is None


def test_rejects_oversized_file():
    ok, msg = s3_store.validate_upload_request("image/png", 20 * 1024 * 1024)
    assert ok is False
    assert "exceeds" in msg


def test_boundary_size_is_allowed():
    ok, _ = s3_store.validate_upload_request("image/png", s3_store.MAX_FILE_SIZE_BYTES)
    assert ok is True
