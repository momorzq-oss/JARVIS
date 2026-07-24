from brain.llm import LLM


def test_extract_json_from_prose_and_nested_strings():
    text = 'Result: {"skill":"chat","params":{"message":"use {braces}"}} done'
    assert LLM.extract_json(text) == {
        "skill": "chat",
        "params": {"message": "use {braces}"},
    }


def test_extract_json_repairs_trailing_commas():
    assert LLM.extract_json('```json\n{"skill":"chat",}\n```') == {"skill": "chat"}


def test_list_models_uses_openrouter_catalog_and_sorts_ids(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"id": "z/model"}, {"id": "a/model"}, {"id": "z/model"}]}

    def get(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr("requests.get", get)
    llm = LLM(api_key="sk-or-v1-test", base_url="https://openrouter.ai/api/v1")

    assert llm.list_models() == ["a/model", "z/model"]
    assert captured["url"] == "https://openrouter.ai/api/v1/models"
    assert captured["headers"]["Authorization"] == "Bearer sk-or-v1-test"
