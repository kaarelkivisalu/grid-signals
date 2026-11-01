"""An explicitly recorded harness amendment cannot conceal other candidate changes."""

import hashlib
import json

import pytest

from grid_signals.forecast.pipelines import holdout


def test_frozen_candidate_rejects_unrecorded_changes(tmp_path, monkeypatch):
    candidate = tmp_path / "candidate.py"
    candidate.write_text("original")
    manifest = {
        "sources": {"candidate.py": hashlib.sha256(candidate.read_bytes()).hexdigest()}
    }
    monkeypatch.setattr(holdout.paths, "ROOT", tmp_path)
    monkeypatch.setattr(holdout, "AMENDMENT", tmp_path / "amendment.json")
    holdout.verify(manifest)
    candidate.write_text("changed")
    with pytest.raises(RuntimeError, match="frozen candidate"):
        holdout.verify(manifest)


def test_amendment_must_match_both_original_and_current_source(tmp_path, monkeypatch):
    source = tmp_path / "runner.py"
    source.write_text("corrected harness")
    amendment = tmp_path / "amendment.json"
    original = hashlib.sha256(b"original harness").hexdigest()
    amendment.write_text(
        json.dumps(
            {
                "sources": {
                    "runner.py": {
                        "original_sha256": original,
                        "amended_sha256": hashlib.sha256(
                            source.read_bytes()
                        ).hexdigest(),
                    }
                }
            }
        )
    )
    monkeypatch.setattr(holdout.paths, "ROOT", tmp_path)
    monkeypatch.setattr(holdout, "AMENDMENT", amendment)
    holdout.verify({"sources": {"runner.py": original}})
    with pytest.raises(RuntimeError, match="does not match"):
        holdout.verify({"sources": {"runner.py": "unrelated release"}})
    source.write_text("additional unrecorded change")
    with pytest.raises(RuntimeError, match="frozen candidate"):
        holdout.verify({"sources": {"runner.py": original}})
