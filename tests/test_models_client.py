from __future__ import annotations

from types import SimpleNamespace

from backend import models_client


def test_chat_json_never_combines_json_response_format_with_thinking(monkeypatch):
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))],
            usage=SimpleNamespace(total_tokens=7),
        )

    monkeypatch.setattr(models_client._client.chat.completions, "create", fake_create)

    result = models_client.chat_json(
        role="arbiter",
        messages=[{"role": "user", "content": "Return JSON."}],
        thinking=True,
    )

    assert result == {"ok": True}
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["model"] == models_client.MODEL_ROLES["arbiter"]
    assert "extra_body" not in captured
