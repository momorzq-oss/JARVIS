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
    def __init__(self, llm, router=None, colibri=None):
        self.llm = llm
        self.router = router
        self.colibri = colibri
        self.state = {}


class _LocalRouter:
    def __init__(self, reply="A local Qwen reply, sir."):
        self.reply = reply
        self.messages = []

    def generate_reply(self, messages, **_kwargs):
        self.messages = messages
        return self.reply


class _LocalColibri:
    configured = True

    def __init__(self):
        self.messages = []

    def complete(self, messages, **_kwargs):
        self.messages = messages
        return "A local Colibri reply, sir."


class _FailingOnlineLLM:
    available = True

    def chat(self, _messages, **_kwargs):
        return ""


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


def test_general_conversation_uses_local_qwen_when_cloud_is_unavailable():
    router = _LocalRouter()
    ctx = _Context(_OfflineLLM(), router=router)

    reply = chat.chat("Explain why the sky looks blue.", "", ctx)

    assert reply == "A local Qwen reply, sir."
    assert router.messages[-1]["content"] == "Explain why the sky looks blue."
    assert ctx.state["chat_provider"] == "local_qwen"


def test_failed_cloud_completion_falls_back_to_local_qwen():
    ctx = _Context(_FailingOnlineLLM(), router=_LocalRouter())

    reply = chat.chat("Help me make a project plan.", "", ctx)

    assert reply == "A local Qwen reply, sir."
    assert ctx.state["chat_provider"] == "local_qwen"


def test_colibri_is_preferred_before_qwen_for_local_generation():
    colibri = _LocalColibri()
    router = _LocalRouter()
    ctx = _Context(_OfflineLLM(), router=router, colibri=colibri)

    reply = chat.chat("Summarize this idea.", "", ctx)

    assert reply == "A local Colibri reply, sir."
    assert colibri.messages[-1]["content"] == "Summarize this idea."
    assert router.messages == []
    assert ctx.state["chat_provider"] == "colibri"


def test_general_conversation_remembers_the_turn_for_follow_up_context():
    llm = _OnlineLLM()
    chat.chat("I want to discuss a new project.", "", _Context(llm))
    chat.chat("What should I consider first?", "", _Context(llm))

    assert {"role": "user", "content": "I want to discuss a new project."} in llm.messages
    assert {"role": "assistant", "content": "A considered reply, sir."} in llm.messages


def test_active_human_conversation_uses_session_history_for_followups():
    from core.conversation import ConversationManager

    llm = _OnlineLLM()
    ctx = _Context(llm)
    ctx.conversation = ConversationManager()
    ctx.conversation.begin(user_text="I am working on the voice system.")
    ctx.conversation.record_assistant("What problem are you having with it?")
    ctx.conversation.record_user("It stops listening after one reply.")

    chat.chat("What should I inspect?", "", ctx)

    assert {"role": "user", "content": "I am working on the voice system."} in llm.messages
    assert {"role": "assistant", "content": "What problem are you having with it?"} in llm.messages
    assert {"role": "user", "content": "It stops listening after one reply."} in llm.messages
