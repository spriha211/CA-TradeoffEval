import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.cross_model_replication.generate import ClaudeAdapter, PROTOCOL_SHA256, controls, sha256_file
from src.cross_model_replication.review_app import latest_reviews
from src.cross_model_replication.scoring import Batch, Suggestion, validate


class FakeResponse:
    model = "claude-test-returned-id"
    content = [SimpleNamespace(type="text", text="parsed answer")]
    usage = SimpleNamespace(input_tokens=12, output_tokens=7)

    def model_dump(self, mode="json"):
        return {"model": self.model, "content": [{"type": "text", "text": "parsed answer"}],
                "usage": {"input_tokens": 12, "output_tokens": 7}}


class FakeStream:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get_final_message(self):
        return self.response


class FakeMessages:
    def __init__(self):
        self.calls = 0

    def stream(self, **kwargs):
        self.calls += 1
        return FakeStream(FakeResponse())


def test_adapter_raw_parsed_checkpoint_and_namespace(tmp_path):
    client = SimpleNamespace(messages=FakeMessages())
    adapter = ClaudeAdapter(client, tmp_path / "study2")
    assert adapter.call("stage", "system", "input") == "parsed answer"
    assert client.messages.calls == 1
    assert (tmp_path / "study2/raw/stage.json").exists()
    assert (tmp_path / "study2/parsed/stage.txt").read_text().strip() == "parsed answer"
    adapter2 = ClaudeAdapter(client, tmp_path / "study2")
    assert adapter2.call("stage", "system", "input") == "parsed answer"
    assert client.messages.calls == 1
    assert not (tmp_path / "runs/raw").exists()


def suggestion(**changes):
    value = dict(blind_id="M03-C001", component_id="M03-C01", suggested_preservation=1,
                 exact_evidence_quote="exact quote", short_reason="supported", confidence=.9,
                 distortion_severity=0, distortion_explanation="", needs_human_review=False)
    value.update(changes)
    return Suggestion(**value)


def job():
    return {"blind_id": "M03-C001", "blinded_answer": "An exact quote is here.",
            "components": [{"component_id": "M03-C01"}]}


def test_invalid_quote_fails_closed():
    batch = validate(
        Batch(
            suggestions=[
                suggestion(
                    exact_evidence_quote="quote that is not in the answer"
                )
            ]
        ),
        job(),
    )
    row = batch.suggestions[0]
    assert (row.suggested_preservation, row.exact_evidence_quote, row.needs_human_review) == (0, "", True)


def test_duplicate_or_missing_rows_rejected():
    with pytest.raises(RuntimeError, match="component set"):
        validate(Batch(suggestions=[suggestion(), suggestion()]), job())


def test_material_distortion_requires_zero():
    with pytest.raises(RuntimeError, match="Material distortion"):
        validate(Batch(suggestions=[suggestion(exact_evidence_quote="exact quote", distortion_severity=2)]), job())


def test_latest_review_event_wins(tmp_path):
    path = tmp_path / "review.jsonl"
    path.write_text('\n'.join([json.dumps({"blind_id":"M03-C001","component_id":"x","flagged":True}),
                               json.dumps({"blind_id":"M03-C001","component_id":"x","flagged":False})]) + '\n')
    assert latest_reviews(path)[('M03-C001', 'x')]['flagged'] is False


def test_controls_match_study1_schedule():
    assert controls("M03", 1) == ([2, 1, 3], 3, 3)


def test_frozen_protocol_hash():
    path = Path("runs/audits/cross_model_replication/STUDY2_PRE_GENERATION_PROTOCOL.json")
    assert sha256_file(path) == PROTOCOL_SHA256
