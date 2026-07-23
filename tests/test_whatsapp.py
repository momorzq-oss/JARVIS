from types import SimpleNamespace

from skills import whatsapp


def test_general_whatsapp_read_uses_current_visible_conversation(monkeypatch):
    window = object()
    ctx = SimpleNamespace(state={})
    monkeypatch.setattr(whatsapp, "_connect_window", lambda: window)
    monkeypatch.setattr(
        whatsapp, "open_chat",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("an empty contact must not start a chat search")
        ),
    )
    monkeypatch.setattr(
        whatsapp, "read_visible_messages", lambda win, limit: ["Visible message"],
    )

    result = whatsapp.read_chat("", ctx)

    assert result == "Latest visible WhatsApp messages, sir: Visible message"
    assert ctx.state["whatsapp_last"] == "Visible message"
    assert "whatsapp_contact" not in ctx.state
