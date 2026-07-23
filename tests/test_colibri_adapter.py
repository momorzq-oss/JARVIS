import pytest

from integrations.colibri_adapter import ColibriAdapter, ColibriError


def test_colibri_is_disabled_by_default():
    adapter = ColibriAdapter(enabled=False)
    with pytest.raises(ColibriError, match="disabled"):
        adapter.health()
    with pytest.raises(ColibriError, match="disabled"):
        adapter.complete("invalid but never transmitted")


def test_colibri_rejects_non_local_endpoint():
    adapter = ColibriAdapter(enabled=True, mode="http_api", base_url="https://example.com/v1")
    with pytest.raises(ColibriError, match="local"):
        adapter.health()


def test_colibri_completion_uses_documented_endpoint(monkeypatch):
    adapter = ColibriAdapter(enabled=True, mode="http_api")
    captured = {}

    def fake_request(method, endpoint, payload=None):
        captured.update(method=method, endpoint=endpoint, payload=payload)
        return {"choices": [{"message": {"content": "local answer"}}]}

    monkeypatch.setattr(adapter, "_request", fake_request)
    assert adapter.complete([{"role": "user", "content": "hello"}]) == "local answer"
    assert captured["method"] == "POST"
    assert captured["endpoint"] == "/chat/completions"
    assert captured["payload"]["stream"] is False
