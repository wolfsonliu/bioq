import hashlib

import httpx
import pytest

from bioq.errors import UsageError
from bioq.upload import sha256_file, upload_files


class _FakeClient:
    def __init__(self, exists=False, put_url="https://put", uri_scheme="oss://b"):
        self._exists = exists
        self._put_url = put_url
        self._uri_scheme = uri_scheme
        self.prepared = []
        self.put_files = []

    def prepare_upload(self, job_id, filename, sha256):
        self.prepared.append((job_id, filename, sha256))
        return {"uri": f"{self._uri_scheme}/users/p/{job_id}/input/{filename}",
                "exists": self._exists,
                "put_url": None if self._exists else self._put_url}

    def put_file(self, url, content):
        self.put_files.append((url, content))


def test_sha256_file(tmp_path):
    f = tmp_path / "x.pdb"
    f.write_bytes(b"ATOM")
    assert sha256_file(f) == hashlib.sha256(b"ATOM").hexdigest()


def test_upload_maps_field_to_uri(tmp_path, monkeypatch):
    f = tmp_path / "c.pdb"
    f.write_bytes(b"ATOM")
    puts = []
    monkeypatch.setattr(httpx, "put",
                        lambda url, content, timeout=None: puts.append(url) or httpx.Response(200))
    client = _FakeClient(exists=False)
    uris = upload_files(client, "j1", [f"input_pdb={f}"])
    assert uris == {"input_pdb_uri": f"oss://b/users/p/j1/input/{f.name}"}
    assert puts == ["https://put"]  # uploaded because exists=False


def test_upload_relative_url_goes_through_client(tmp_path, monkeypatch):
    # file storage backend: prepare_upload returns a gateway-relative URL, which
    # must be PUT through the authed client session, not via bare httpx.put.
    f = tmp_path / "c.pdb"
    f.write_bytes(b"ATOM")
    monkeypatch.setattr(httpx, "put",
                        lambda *a, **k: pytest.fail("bare httpx.put used for relative URL"))
    client = _FakeClient(exists=False, put_url="/v1/files/users/p/j1/input/c.pdb",
                         uri_scheme="file:///data")
    uris = upload_files(client, "j1", [f"model={f}"])
    assert uris == {"model_uri": f"file:///data/users/p/j1/input/{f.name}"}
    assert client.put_files == [("/v1/files/users/p/j1/input/c.pdb", b"ATOM")]


def test_upload_skips_when_exists(tmp_path, monkeypatch):
    f = tmp_path / "c.pdb"
    f.write_bytes(b"ATOM")
    puts = []
    monkeypatch.setattr(httpx, "put",
                        lambda url, content, timeout=None: puts.append(url))
    client = _FakeClient(exists=True)
    uris = upload_files(client, "j1", [f"input_pdb={f}"])
    assert uris == {"input_pdb_uri": f"oss://b/users/p/j1/input/{f.name}"}
    assert puts == []  # dedup: no PUT


def test_multi_file_same_field_becomes_list(tmp_path, monkeypatch):
    a = tmp_path / "a.pdb"
    a.write_bytes(b"A")
    b = tmp_path / "b.pdb"
    b.write_bytes(b"B")
    monkeypatch.setattr(httpx, "put", lambda url, content, timeout=None: httpx.Response(200))
    uris = upload_files(_FakeClient(), "j1", [f"refs={a}", f"refs={b}"])
    assert isinstance(uris["refs_uri"], list) and len(uris["refs_uri"]) == 2


def test_bad_file_arg_raises(tmp_path):
    with pytest.raises(UsageError):
        upload_files(_FakeClient(), "j1", ["noequals"])


def test_missing_file_raises(tmp_path):
    with pytest.raises(UsageError):
        upload_files(_FakeClient(), "j1", [f"input_pdb={tmp_path/'ghost.pdb'}"])


def test_put_timeout_is_single_sourced():
    from bioq.client import PUT_TIMEOUT
    from bioq.upload import PUT_TIMEOUT as upload_timeout
    assert upload_timeout is PUT_TIMEOUT
