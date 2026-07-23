from types import SimpleNamespace

import pytest

from core.command_context import record_result
from core.command_pipeline import select_route
from core.command_trace import build_trace


class NoCloudRouter:
    def __init__(self):
        self.calls = 0
        self.load_error = "offline"

    def classify(self, text):
        self.calls += 1
        return {"skill": "chat", "params": {"message": text}}


def context(*, pending=None, state=None):
    return SimpleNamespace(
        pending=pending,
        state=state or {},
        router=NoCloudRouter(),
        action_manager=None,
        assistant_controller=None,
    )


RESEARCH_PHRASES = [
    "Create research about artificial intelligence.",
    "Make a research report about AI.",
    "Research renewable energy.",
    "Investigate quantum computing and produce a report.",
    "Prepare a detailed study about machine learning.",
    "Write a complete research paper about the history of robotics.",
    "Produce a cited report about local language models.",
    "Look into battery storage and write the findings.",
    "Study solar power adoption and prepare a report.",
    "Create an analysis of edge AI.",
    "Draft a research brief about climate technology.",
    "Make a source-grounded report about autonomous vehicles.",
    "Find reliable information about fusion energy and produce a report.",
    "Investigate medical robotics and prepare a paper.",
    "Research the history of the internet.",
    "Please research sustainable aviation fuel.",
    "Could you investigate privacy-preserving AI and write a report?",
    "Would you prepare a study about smart cities?",
    "Kindly create research about cybersecurity education.",
    "Write a literature review about federated learning.",
    "Prepare an analysis of renewable desalination.",
    "Look into local LLM education and produce a brief.",
    "Make a research paper about humanoid robots.",
    "Create a cited study about ocean energy.",
    "Research carbon capture and prepare the findings.",
]


@pytest.mark.parametrize("phrase", RESEARCH_PHRASES)
def test_research_phrasings_use_the_shared_deterministic_route(phrase):
    ctx = context()
    route = select_route(phrase, ctx)
    assert route["selected_engine"] == "deterministic"
    assert route["intent"]["skill"] in {
        "research.create_report", "office_word.create_research_document",
    }
    assert ctx.router.calls == 0


WORD_CREATION_PHRASES = [
    "Create a Word document.",
    "Make a Word file.",
    "Open a blank Word document.",
    "Start a new Microsoft Word document.",
    "Launch a blank Word file.",
    "Please create a new Word doc.",
    "Could you make a blank document in Word?",
    "Would you open a new Microsoft Word file?",
    "Kindly prepare a Word document.",
    "Bring up a new Word document.",
    "Open Word and create a report about quantum computing.",
    "Create a research report about AI in Word.",
    "Write a study about robotics using Microsoft Word.",
    "Prepare a cited report about clean energy in Word.",
    "Look into local LLMs and write the findings in Word.",
    "Investigate battery technology and make a Word report.",
    "Make a research paper about cybersecurity in Word.",
    "Create an analysis of edge computing in Microsoft Word.",
    "Produce a source-grounded brief about solar cells in Word.",
    "Research digital twins and create a document in Word.",
]


@pytest.mark.parametrize("phrase", WORD_CREATION_PHRASES)
def test_word_creation_phrasings_stay_local(phrase):
    ctx = context()
    route = select_route(phrase, ctx)
    assert route["selected_engine"] == "deterministic"
    assert route["intent"]["skill"] in {
        "office_word.create_document", "office_word.create_research_document",
    }
    assert ctx.router.calls == 0


LIVE_PHRASES = [
    "Create a research report about AI live in Word.",
    "Write a report about robotics visibly in Microsoft Word.",
    "Research solar power and type it live in Word.",
    "Make a cited study about batteries while I watch in Word.",
    "Prepare a report about local LLMs so I can watch you type it in Word.",
    "Open Word and create a full report about quantum computing live.",
    "Investigate edge AI and write the findings visibly in Word.",
    "Create a research paper about aviation in front of me.",
    "Write a source-grounded report about desalination progressively in Word.",
    "Make a report about renewable energy word by word in Word.",
    "Prepare a study about privacy sentence by sentence in Word.",
    "Research smart cities and let me see you type it in Word.",
    "Produce a cited brief about robotics while I watch.",
    "Look into fusion energy and create it visibly in Word.",
    "Open Microsoft Word and create a complete research report about AI. Type it live so I can watch.",
]


@pytest.mark.parametrize("phrase", LIVE_PHRASES)
def test_live_mode_phrasings_select_one_word_workflow(phrase):
    route = select_route(phrase, context())
    assert route["intent"]["skill"] == "office_word.create_research_document"
    assert route["intent"]["params"]["execution_mode"] == "LIVE_INTERACTIVE"


FOLDER_APP_PHRASES = [
    ("Open Downloads", "app.open_folder"),
    ("Please show me my Downloads folder", "app.open_folder"),
    ("Could you take me to Documents?", "app.open_folder"),
    ("Bring up my Pictures directory", "app.open_folder"),
    ("Go to OneDrive", "app.open_folder"),
    ("I want to open the Desktop folder", "app.open_folder"),
    ("Access my Music folder", "app.open_folder"),
    ("Display the Videos directory", "app.open_folder"),
    ("Navigate to This PC", "app.open_folder"),
    ("Show the Recycle Bin", "app.open_folder"),
    ("Open Word", "app.open"),
    ("Would you launch Microsoft Word for me?", "app.open"),
    ("Bring up Excel", "app.open"),
    ("Please start PowerPoint", "app.open"),
    ("Fire up Notepad", "app.open"),
    ("Could you open Calculator?", "app.open"),
    ("Pull up File Explorer", "app.open"),
    ("I need to launch Chrome", "app.open"),
    ("Start Outlook for me", "app.open"),
    ("Load OneNote", "app.open"),
]


@pytest.mark.parametrize(("phrase", "skill"), FOLDER_APP_PHRASES)
def test_folder_and_application_aliases_share_one_route(phrase, skill):
    ctx = context()
    assert select_route(phrase, ctx)["intent"]["skill"] == skill
    assert ctx.router.calls == 0


def test_explicit_windows_folder_path_outranks_alias_inside_path():
    path = r"C:\Users\Burab\OneDrive\Desktop\JARVIS\.test_tmp\folder probe"
    route = select_route(f"Please show me the folder {path}", context())

    assert route["intent"] == {
        "skill": "app.open_folder", "params": {"target": path},
    }


def test_quoted_windows_folder_path_preserves_spaces():
    path = r"C:\Users\Burab\OneDrive\Desktop\Course Work"
    route = select_route(f'Open the folder "{path}" for me', context())

    assert route["intent"] == {
        "skill": "app.open_folder", "params": {"target": path},
    }


BROWSER_PHRASES = [
    ("Open browser", "browser.open"),
    ("I need to browse the web", "browser.open"),
    ("Open Google", "browser.open_site"),
    ("Bring up YouTube", "browser.open_site"),
    ("Search Google for local LLM education", "web.search"),
    ("Look for quantum computing tutorials", "web.search"),
    ("Find me an article about edge AI", "web.search"),
    ("Open Google and look up battery storage", "web.search"),
    ("Can you find information about solar cells?", "web.search"),
    ("Search for Python packaging", "web.search"),
    ("Search YouTube for local LLMs", "browser.search_youtube"),
    ("Look on YouTube for an AI tutorial", "browser.search_youtube"),
    ("Find a video explaining solar power", "browser.search_youtube"),
    ("Play an educational video about robotics", "browser.search_youtube_and_play"),
    ("Show me the best tutorial for running an LLM locally", "browser.search_youtube"),
    ("Open a new tab and search for AI safety", "web.search"),
    ("YouTube battery technology", "browser.search_youtube"),
    ("Watch a useful lesson about calculus", "browser.search_youtube_and_play"),
    ("Go back", "browser.back"),
    ("Open a new tab", "browser.new_tab"),
]


@pytest.mark.parametrize(
    ("phrase", "expected_query"),
    [
        ("Find a relaxing piano video on YouTube and play the first good result.", "relaxing piano"),
        ("Search YouTube for jazz and play the first video", "jazz"),
        ("Find a robotics tutorial and open the best result", "robotics"),
    ],
)
def test_browser_result_selection_is_not_part_of_the_search_topic(phrase, expected_query):
    route = select_route(phrase, context())

    assert route["intent"]["skill"] == "browser.search_youtube_and_play"
    assert route["intent"]["params"]["query"] == expected_query


@pytest.mark.parametrize(("phrase", "skill"), BROWSER_PHRASES)
def test_browser_and_search_phrasings_share_one_route(phrase, skill):
    ctx = context()
    assert select_route(phrase, ctx)["intent"]["skill"] == skill
    assert ctx.router.calls == 0


CLOSE_PHRASES = [
    ("Close it", "app.close"),
    ("Close it again", "app.close"),
    ("Close it again, please.", "app.close"),
    ("Close that now please", "app.close"),
    ("Could you close the application?", "app.close"),
    ("Close Word", "app.close"),
    ("Exit Microsoft Word", "app.close"),
    ("Quit Excel", "app.close"),
    ("Close PowerPoint", "app.close"),
    ("Shut Notepad", "app.close"),
    ("Exit Calculator", "app.close"),
    ("Close the folder", "app.close"),
    ("Shut the directory", "app.close"),
    ("Close the folder I just opened", "app.close"),
    ("Shut the directory you recently opened", "app.close"),
    ("Close my most recently opened folder", "app.close"),
    ("Close this tab", "browser.close_tab"),
    ("Close the current tab", "browser.close_tab"),
    ("Shut the YouTube tab", "browser.close_tab"),
    ("Exit the Google page", "browser.close_tab"),
    ("Close the browser", "browser.close"),
    ("Exit Chrome", "browser.close"),
    ("Quit Google Chrome", "browser.close"),
    ("Close Outlook", "app.close"),
    ("Close OneNote", "app.close"),
    ("Close File Explorer", "app.close"),
]


@pytest.mark.parametrize(("phrase", "skill"), CLOSE_PHRASES)
def test_close_phrasings_share_one_route(phrase, skill):
    ctx = context()
    assert select_route(phrase, ctx)["intent"]["skill"] == skill
    assert ctx.router.calls == 0


@pytest.mark.parametrize(
    "phrase",
    (
        "Close the folder I just opened",
        "Shut the directory you recently opened",
        "Close my most recently opened folder",
    ),
)
def test_recent_folder_followups_resolve_to_owned_resource_sentinel(phrase):
    ctx = context(state={"command_context": {
        "current_folder": "Downloads",
        "current_application": "File Explorer",
    }})

    intent = select_route(phrase, ctx)["intent"]

    assert intent == {
        "skill": "app.close",
        "params": {"target": "__recent_folder__"},
    }
    record_result(ctx.state, intent, "Closed the folder, sir.")
    assert ctx.state["command_context"]["current_folder"] == ""
    assert ctx.state["command_context"]["current_application"] == ""


@pytest.mark.parametrize(
    "phrase",
    (
        "Close it", "Close it again", "Close it again, please.",
        "Close that now please", "Would you close that for me?",
        "Now close it, please.", "And now close it for me.",
    ),
)
def test_contextual_close_modifiers_resolve_to_recent_owned_folder(phrase):
    ctx = context(state={"command_context": {
        "current_folder": "Downloads",
        "current_application": "File Explorer",
    }})

    intent = select_route(phrase, ctx)["intent"]

    assert intent == {
        "skill": "app.close",
        "params": {"target": "__recent_folder__"},
    }


def test_context_followup_uses_current_word_application_without_cloud():
    ctx = context()
    opened = select_route("Open Word", ctx)["intent"]
    record_result(ctx.state, opened, "Microsoft Word opened, sir.")
    followup = select_route("Create a research report about AI", ctx)
    assert followup["intent"]["skill"] == "office_word.create_research_document"
    assert followup["intent"]["params"]["topic"] == "AI"
    assert ctx.router.calls == 0


@pytest.mark.parametrize(
    ("phrase", "expected"),
    (
        ("Could you open WhatsApp for me?", {
            "skill": "whatsapp.open", "params": {},
        }),
        ("Check my WhatsApp messages", {
            "skill": "whatsapp.read", "params": {"contact": ""},
        }),
        ("Read my WhatsApp chat with Alice", {
            "skill": "whatsapp.read", "params": {"contact": "Alice"},
        }),
        ("What did Alice say on WhatsApp?", {
            "skill": "whatsapp.read", "params": {"contact": "Alice"},
        }),
        ("Send Alice a WhatsApp message saying hello", {
            "skill": "whatsapp.reply",
            "params": {"contact": "Alice", "message": "hello"},
        }),
        ("Reply to Alice on WhatsApp and say hello", {
            "skill": "whatsapp.reply",
            "params": {"contact": "Alice", "message": "hello"},
        }),
    ),
)
def test_whatsapp_language_uses_shared_local_extraction(phrase, expected):
    ctx = context()

    route = select_route(phrase, ctx)

    assert route["intent"] == expected
    assert route["selected_engine"] == "deterministic"
    assert ctx.router.calls == 0


def test_whatsapp_contextual_reply_reuses_verified_current_contact():
    ctx = context(state={"whatsapp_contact": "Alice"})

    route = select_route("Reply to them saying I will call later", ctx)

    assert route["intent"] == {
        "skill": "whatsapp.reply",
        "params": {"contact": "Alice", "message": "I will call later"},
    }
    assert ctx.router.calls == 0


def test_office_creation_topic_drops_delivery_application_suffix():
    presentation = select_route(
        "Put together a four-slide presentation about local AI education in PowerPoint",
        context(),
    )["intent"]
    spreadsheet = select_route(
        "Make a budget for student expenses in Microsoft Excel",
        context(),
    )["intent"]

    assert presentation["skill"] == "office.create_presentation"
    assert presentation["params"]["topic"] == "local AI education"
    assert presentation["params"]["slides"] == 4
    assert spreadsheet["skill"] == "office.create_spreadsheet"
    assert spreadsheet["params"]["topic"] == "student expenses"


def test_supplied_word_text_and_explicit_save_use_local_context():
    ctx = context(state={
        "command_context": {"current_application": "Microsoft Word"},
    })
    insert = select_route(
        "Type this paragraph: JARVIS local command validation passed.", ctx,
    )
    save = select_route(
        r"Save it to .test_tmp\jarvis_word_command_validation.docx", ctx,
    )
    assert insert["intent"] == {
        "skill": "office_word.insert_text",
        "params": {"text": "JARVIS local command validation passed."},
    }
    assert save["intent"]["skill"] == "office_word.save_document"
    assert save["intent"]["params"]["path"].endswith(
        r"jarvis_word_command_validation.docx"
    )
    assert ctx.router.calls == 0


@pytest.mark.parametrize(
    "phrase",
    (
        r"Save this to .test_tmp\contextual_save.docx",
        r"Save this document to .test_tmp\contextual_save.docx",
        r"Save the document to .test_tmp\contextual_save.docx",
        r"Save the file to .test_tmp\contextual_save.docx",
    ),
)
def test_word_save_noun_variants_share_local_context(phrase):
    ctx = context(state={
        "command_context": {"current_application": "Microsoft Word"},
    })

    intent = select_route(phrase, ctx)["intent"]

    assert intent == {
        "skill": "office_word.save_document",
        "params": {"path": r".test_tmp\contextual_save.docx"},
    }
    assert ctx.router.calls == 0


def test_local_command_preempts_research_pending_and_offline_services():
    ctx = context(pending={"kind": "research"})
    route = select_route("Please show me my Downloads folder", ctx)
    assert route["route_type"] == "intent"
    assert route["intent"]["skill"] == "app.open_folder"
    assert ctx.router.calls == 0


def test_close_word_stays_in_unsaved_save_dialogue():
    ctx = context(pending={"kind": "save_document", "request": object()})

    route = select_route("Close Word", ctx)

    assert route["route_type"] == "pending"
    assert route["pending_kind"] == "save_document"


def test_office_creation_strips_polite_request_scaffolding_consistently():
    spreadsheet = select_route(
        "Please build a monthly budget tracker in Excel.", context()
    )["intent"]
    presentation = select_route(
        "Could you create a five-slide presentation about local AI?", context()
    )["intent"]
    document = select_route(
        "Kindly draft a report about regional transport.", context()
    )["intent"]

    assert spreadsheet["skill"] == "office.create_spreadsheet"
    assert spreadsheet["params"]["topic"] == "monthly budget tracker"
    assert presentation["skill"] == "office.create_presentation"
    assert presentation["params"]["topic"] == "local AI"
    assert document["skill"] == "office.create_document"
    assert document["params"]["topic"] == "regional transport"


def test_general_word_proposal_does_not_enter_university_mode():
    intent = select_route(
        "Create a short Word proposal about employee training.", context(),
    )["intent"]

    assert intent["skill"] == "office.create_document"
    assert intent["params"]["document_type"] == "proposal"
    assert intent["params"]["topic"] == "employee training"


def test_university_topic_proposal_stays_in_general_office_route():
    intent = select_route(
        "Create a detailed proposal about university student support visibly in Word.",
        context(),
    )["intent"]

    assert intent["skill"] == "office.create_document"
    assert intent["params"]["document_type"] == "proposal"
    assert intent["params"]["topic"] == "university student support"
    assert intent["params"]["mode"] == "structured"


def test_brief_adjective_does_not_turn_proposal_into_research_report():
    intent = select_route(
        "Create a brief proposal about campus mentoring visibly in Word.",
        context(),
    )["intent"]

    assert intent["skill"] == "office.create_document"
    assert intent["params"]["document_type"] == "proposal"
    assert intent["params"]["topic"] == "campus mentoring"
    assert intent["params"]["mode"] == "structured"


def test_brief_noun_still_routes_to_short_research_document():
    intent = select_route(
        "Create a brief about campus mentoring live in Word.", context(),
    )["intent"]

    assert intent["skill"] == "office_word.create_research_document"
    assert intent["params"]["topic"] == "campus mentoring"
    assert intent["params"]["report_length"] == "short"


def test_exact_office_product_nouns_keep_flexible_creation_verbs():
    spreadsheet = select_route(
        "Prepare an Excel spreadsheet for quarterly expenses", context(),
    )["intent"]
    presentation = select_route(
        "Prepare a five-slide PowerPoint presentation about safe local AI",
        context(),
    )["intent"]

    assert spreadsheet["skill"] == "office.create_spreadsheet"
    assert spreadsheet["params"]["topic"] == "quarterly expenses"
    assert presentation["skill"] == "office.create_presentation"
    assert presentation["params"]["topic"] == "safe local AI"
    assert presentation["params"]["slides"] == 5


@pytest.mark.parametrize(
    ("phrase", "skill"),
    [
        ("Minimize it", "window.minimize"),
        ("Maximize that window", "window.maximize"),
        ("Restore the current window", "window.restore"),
        ("Bring it to the front", "window.front"),
        ("Bring it back up", "window.front"),
        ("Now bring it back, please.", "window.front"),
        ("Focus on this window", "window.focus"),
    ],
)
def test_window_followups_resolve_active_application(phrase, skill):
    ctx = context()
    ctx.state["command_context"] = {"current_application": "Calculator"}

    assert select_route(phrase, ctx)["intent"] == {
        "skill": skill, "params": {"target": "Calculator"},
    }


def test_natural_research_followup_remains_in_pending_research_context():
    ctx = context(pending={"kind": "research"})
    route = select_route("What sources have we gathered?", ctx)
    assert route["route_type"] == "pending"
    assert route["pending_kind"] == "research"


@pytest.mark.parametrize(
    "phrase",
    (
        "Start a new research project about grid-scale battery storage.",
        "Begin a research session on grid-scale battery storage.",
        "Let's create a new research project regarding grid-scale battery storage.",
    ),
)
def test_interactive_research_project_phrasing_stays_local(phrase):
    ctx = context()

    intent = select_route(phrase, ctx)["intent"]

    assert intent == {
        "skill": "research.start",
        "params": {"topic": "grid-scale battery storage"},
    }
    assert ctx.router.calls == 0


def test_trace_validates_without_executing_or_calling_cloud():
    ctx = context()
    trace = build_trace("Please show me my Downloads folder", ctx)
    assert trace["selected_engine"] == "deterministic"
    assert trace["capability_id"] == "app.open_folder"
    assert trace["schema_result"] == "valid"
    assert trace["allowlist_result"] == "allowed"
    assert ctx.router.calls == 0


def test_trace_command_is_not_spoken_as_a_long_json_payload(monkeypatch):
    from core.assistant_controller import AssistantController

    fake_ctx = context()
    fake_ctx.speaker = SimpleNamespace(
        speak=lambda *args, **kwargs: None,
        stop=lambda: None,
        speaking=False,
    )
    fake_ctx.registry = SimpleNamespace(get_status=lambda: [])
    fake_ctx.llm = SimpleNamespace(available=False)
    fake_ctx.live_task = None
    fake_ctx.browser = SimpleNamespace(_page=None)
    ctl = AssistantController(ctx=fake_ctx, skip_preload=True)
    spoken = []
    monkeypatch.setattr(ctl, "speak", lambda text, block=False: spoken.append(text))
    result = ctl.handle_text("/trace Open Downloads")
    assert '"capability_id": "app.open_folder"' in result
    assert spoken == []


def test_emergency_stop_completion_is_visual_but_does_not_restart_speech(monkeypatch):
    import main as main_mod

    spoken = []
    fake_ctx = context(state={})
    fake_ctx.speaker = SimpleNamespace(
        speak=lambda text, block=False: spoken.append(text),
        stop=lambda: None,
        speaking=False,
    )
    monkeypatch.setattr(
        main_mod,
        "dispatch",
        lambda intent, routed_ctx: (
            "Emergency stop completed. All automation input was released."
        ),
    )

    result = main_mod.handle_utterance("Emergency stop", fake_ctx)

    assert result.startswith("Emergency stop completed")
    assert spoken == []


def test_emergency_stop_suppresses_late_response_from_active_command(monkeypatch):
    import main as main_mod

    spoken = []
    fake_ctx = context(state={"emergency_stop_generation": 0})
    fake_ctx.speaker = SimpleNamespace(
        speak=lambda text, block=False: spoken.append(text),
        stop=lambda: None,
        speaking=False,
    )

    def interrupted_dispatch(_intent, routed_ctx):
        routed_ctx.state["emergency_stop_generation"] += 1
        return "The interrupted task was cancelled."

    monkeypatch.setattr(main_mod, "dispatch", interrupted_dispatch)

    result = main_mod.handle_utterance("Open Notepad", fake_ctx)

    assert result == "The interrupted task was cancelled."
    assert spoken == []


def test_emergency_dispatch_cancels_controller_owned_hermes_adapter():
    import main as main_mod

    stopped = []
    ctx = SimpleNamespace(
        speaker=SimpleNamespace(stop=lambda: stopped.append("speech")),
        live_task=None,
        assistant_controller=SimpleNamespace(
            stop_task=lambda: stopped.append("controller"),
        ),
        web_automation=SimpleNamespace(
            emergency_stop=lambda: stopped.append("browser"),
        ),
    )

    result = main_mod._dispatch_registered(
        {"skill": "system.emergency_stop", "params": {}}, ctx,
    )

    assert stopped == ["speech", "controller", "browser"]
    assert result.startswith("Emergency stop completed")


@pytest.mark.parametrize(("phrase", "skill"), [
    ("Hermes, are you connected?", "hermes.status"),
    ("Show me the Hermes health", "hermes.status"),
    ("What is Hermes doing?", "hermes.tasks"),
    ("What tasks are running?", "hermes.tasks"),
    ("Pause task one", "hermes.pause"),
    ("Continue Hermes task 2", "hermes.resume"),
    ("Cancel Hermes task current", "hermes.cancel"),
    ("Approve Hermes task one", "hermes.approve"),
    ("Reject Hermes task 2", "hermes.deny"),
])
def test_hermes_commands_use_shared_deterministic_route(phrase, skill):
    ctx = context()

    route = select_route(phrase, ctx)

    assert route["selected_engine"] == "deterministic"
    assert route["intent"]["skill"] == skill
    assert ctx.router.calls == 0


@pytest.mark.parametrize(("phrase", "goal", "background"), [
    (
        "Ask Hermes to research three public sources about renewable energy",
        "research three public sources about renewable energy", False,
    ),
    (
        "Give Hermes a task to prepare a short Word report",
        "prepare a short Word report", False,
    ),
    (
        "/goal Research the leading AI automation channels",
        "Research the leading AI automation channels", False,
    ),
    (
        "/background Research current renewable-energy developments",
        "Research current renewable-energy developments", True,
    ),
])
def test_hermes_goal_phrasings_extract_data_only(phrase, goal, background):
    ctx = context()

    intent = select_route(phrase, ctx)["intent"]

    assert intent == {
        "skill": "hermes.plan",
        "params": {"goal": goal, "background_requested": background},
    }
    assert ctx.router.calls == 0
