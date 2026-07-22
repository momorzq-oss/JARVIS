from core.account_connections import AccountConnectionManager
import json


class FakePage:
    url = "https://mail.google.com/mail/u/0/#inbox"

    @staticmethod
    def query_selector(selector):
        return object() if "body" in selector else None


class FakeBrowser:
    def __init__(self):
        self._context = type("Context", (), {"pages": [FakePage()]})()

    def open_site(self, *_args, **_kwargs):
        return FakePage()


class FakeContext:
    browser = FakeBrowser()


def test_gmail_verification_records_non_secret_connection_state(monkeypatch, tmp_path):
    monkeypatch.setattr("core.account_connections.CONNECTION_FILE", tmp_path / "accounts.json")
    manager = AccountConnectionManager(FakeContext())

    result = manager.verify("gmail")

    assert result["connected"] is True
    assert "verified" in result["detail"].lower()
    assert "token" not in (tmp_path / "accounts.json").read_text(encoding="utf-8").lower()


def test_unknown_account_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr("core.account_connections.CONNECTION_FILE", tmp_path / "accounts.json")
    result = AccountConnectionManager(FakeContext()).begin_login("unknown")
    assert result["state"] == "ERROR"


def test_whatsapp_desktop_probe_records_only_verified_connection(monkeypatch, tmp_path):
    monkeypatch.setattr("core.account_connections.CONNECTION_FILE", tmp_path / "accounts.json")

    class Completed:
        stdout = json.dumps({
            "visible": True,
            "connected": True,
            "detail": "WhatsApp Desktop session verified.",
        })

    monkeypatch.setattr("core.account_connections.subprocess.run", lambda *a, **k: Completed())
    result = AccountConnectionManager(FakeContext()).verify("whatsapp")

    assert result["connected"] is True
    stored = (tmp_path / "accounts.json").read_text(encoding="utf-8")
    assert "token" not in stored.lower()
    assert "cookie" not in stored.lower()
