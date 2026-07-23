from skills import office_service


class FakeDocument:
    def __init__(self):
        self.close_calls = []

    def Close(self, **kwargs):
        self.close_calls.append(kwargs)


class FakeDocuments:
    def __init__(self, document):
        self.document = document

    def Add(self):
        return self.document


class FakeWord:
    def __init__(self):
        self.Visible = False
        self.document = FakeDocument()
        self.Documents = FakeDocuments(self.document)
        self.quit_calls = 0

    def Quit(self):
        self.quit_calls += 1


def test_reused_word_session_closes_only_the_jarvis_document(monkeypatch):
    app = FakeWord()
    monkeypatch.setattr(office_service, "_word_com", lambda: (app, False))
    service = office_service.WordService()

    service.open(visible=True)
    service.new_document()
    service.close(save=False)

    assert app.Visible is True
    assert app.document.close_calls == [{"SaveChanges": 0}]
    assert app.quit_calls == 0


def test_owned_word_session_quits_after_closing_its_document(monkeypatch):
    app = FakeWord()
    monkeypatch.setattr(office_service, "_word_com", lambda: (app, True))
    service = office_service.WordService()

    service.open(visible=True)
    service.new_document()
    service.close(save=False)

    assert app.document.close_calls == [{"SaveChanges": 0}]
    assert app.quit_calls == 1
