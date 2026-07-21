import json
from bioq.output import emit


def test_json_mode(capsys):
    emit({"a": 1}, fmt="json")
    out = capsys.readouterr().out
    assert json.loads(out) == {"a": 1}


def test_pretty_dict(capsys):
    emit({"job_id": "j1", "status": "completed"}, fmt="pretty")
    out = capsys.readouterr().out
    assert "job_id" in out and "j1" in out


def test_pretty_list(capsys):
    emit(["a", "b"], fmt="pretty")
    out = capsys.readouterr().out
    assert "a" in out and "b" in out
