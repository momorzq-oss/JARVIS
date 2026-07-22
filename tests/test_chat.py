from skills import chat


class _OfflineLLM:
    available = False


class _OnlineLLM:
    available = True

    def __init__(self):
        self.messages = []

    def chat(self, messages, **_kwargs):
        self.messages = messages
        return "A considered reply, sir."


class _Context:
    def __init__(self, llm):
        self.llm = llm


def setup_function():
    chat._history.clear()


def test_time_conversation_is_local_and_includes_a_time():
    reply = chat.chat("Can you tell me the current time?", "", _Context(_OfflineLLM()))

    assert "It is" in reply
    assert ":" in reply


def test_general_conversation_uses_the_configured_conversation_provider():
    llm = _OnlineLLM()
    reply = chat.chat("Let's discuss how to make a project plan.", "", _Context(llm))

    assert reply == "A considered reply, sir."
    assert llm.messages[-1] == {
        "role": "user", "content": "Let's discuss how to make a project plan."
    }


def test_general_conversation_remembers_the_turn_for_follow_up_context():
    llm = _OnlineLLM()
    chat.chat("I want to discuss a new project.", "", _Context(llm))
    chat.chat("What should I consider first?", "", _Context(llm))

    assert {"role": "user", "content": "I want to discuss a new project."} in llm.messages
    assert {"role": "assistant", "content": "A considered reply, sir."} in llm.messages
