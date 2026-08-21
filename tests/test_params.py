import pytest

from bioq.errors import UsageError
from bioq.params import build_body


def test_set_type_inference():
    body = build_body(sets=["n=2", "temp=0.1", "flag=true", "off=false", "name=gw"],
                      set_jsons=[], file_uris={})
    assert body == {"n": 2, "temp": 0.1, "flag": True, "off": False, "name": "gw"}


def test_set_json_inline_and_file(tmp_path):
    f = tmp_path / "seqs.json"
    f.write_text('[{"id": "A", "sequence": "MK"}]', encoding="utf-8")
    body = build_body(
        sets=[],
        set_jsons=["sequences=@" + str(f), "opts={\"a\": 1}"],
        file_uris={},
    )
    assert body["sequences"] == [{"id": "A", "sequence": "MK"}]
    assert body["opts"] == {"a": 1}


def test_file_uris_merged():
    body = build_body(sets=["name=x"], set_jsons=[],
                      file_uris={"input_pdb_uri": "oss://b/k"})
    assert body == {"name": "x", "input_pdb_uri": "oss://b/k"}


def test_bad_pair_raises_usage():
    with pytest.raises(UsageError):
        build_body(sets=["noequals"], set_jsons=[], file_uris={})
