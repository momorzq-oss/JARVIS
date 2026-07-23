import sys
import os
# Add current directory to path for module imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
import os
import json
from unittest.mock import Mock, patch

from core.action_manager import Action, ActionManager
from config import Config

# Mock Config paths for testing
@pytest.fixture(autouse=True)
def mock_config_paths(tmp_path):
    original_audit_log_file = Config.AUDIT_LOG_FILE
    Config.AUDIT_LOG_FILE = tmp_path / "audit_log.json"
    yield
    Config.AUDIT_LOG_FILE = original_audit_log_file

# Mock audio_log to prevent actual audio logging during tests
@pytest.fixture(autouse=True)
def mock_audio_log():
    with patch('voice.audio_log.log') as mock_log:
        with patch('voice.audio_log.log_error') as mock_log_error:
            yield mock_log, mock_log_error

@pytest.fixture
def mock_controller():
    # Mock the controller and agent objects that ActionManager depends on
    mock_agent = Mock()
    mock_agent.confirm.return_value = True  # Default to approving confirmations
    mock_controller = Mock()
    mock_controller.agent = mock_agent
    mock_controller.speak = Mock() # Mock the speak method
    return mock_controller

@pytest.fixture
def action_manager(mock_controller):
    return ActionManager(mock_controller)


# --- Test Action Schema Validation ---
def test_action_validation_success(action_manager):
    action = Action(
        action_id="123",
        skill="test_skill",
        operation="test_operation",
        parameters={"key": "value"},
        risk_level="low"
    )
    action_manager.validate_action(action) # Should not raise an exception

def test_action_validation_missing_action_id(action_manager):
    action = Action(
        action_id="",
        skill="test_skill",
        operation="test_operation",
        parameters={},
        risk_level="low"
    )
    with pytest.raises(ValueError, match="action_id must be a non-empty string"):
        action_manager.validate_action(action)

def test_action_validation_invalid_risk_level(action_manager):
    action = Action(
        action_id="123",
        skill="test_skill",
        operation="test_operation",
        parameters={},
        risk_level="unknown"
    )
    with pytest.raises(ValueError, match="risk_level must be one of 'low', 'medium', 'high', 'critical'"):
        action_manager.validate_action(action)


# --- Test Permission Scope Assignment ---
@pytest.mark.parametrize("operation, expected_scope", [
    ("read_email", "SAFE_READ"),
    ("delete_file", "FILE_DELETE"),
    ("send_email", "EMAIL_SEND"),
    ("navigate_browser", "BROWSER_NAVIGATE"),
    ("open_app", "DESKTOP_CONTROL"),
    ("edit_document", "FILE_MODIFY"), # Falls under generic modify
    ("perform_security_scan", "SECURITY_CHANGE"),
    ("shutdown_system", "SYSTEM_POWER"),
    ("run_as_admin", "ADMINISTRATOR"),
    ("create_temp_file", "SAFE_WRITE"),
    ("unknown_op", "SAFE_READ"), # Default if no match
])
def test_assign_permission_scope(action_manager, operation, expected_scope):
    action = Action(
        action_id="123",
        skill="test_skill",
        operation=operation,
        parameters={}
    )
    action_manager.assign_permission_scope(action)
    assert action.permission_scope == expected_scope

def test_assign_permission_scope_predefined(action_manager):
    action = Action(
        action_id="123",
        skill="test_skill",
        operation="delete_file",
        parameters={},
        permission_scope="DESKTOP_CONTROL" # Pre-defined scope
    )
    action_manager.assign_permission_scope(action)
    assert action.permission_scope == "DESKTOP_CONTROL"


# --- Test Confirmation Logic ---
def test_requires_confirmation_explicit(action_manager):
    action = Action(
        action_id="123",
        skill="test_skill",
        operation="some_op",
        parameters={},
        requires_confirmation=True
    )
    assert action_manager.requires_confirmation(action) is True

def test_requires_confirmation_via_rules(action_manager, mock_config_paths):
    # Ensure Config.CONFIRMATION_RULES is set correctly for testing
    Config.CONFIRMATION_RULES["confirmation_required"] = ["DELETE_FILES", "SEND_EMAIL"]
    action = Action(
        action_id="123",
        skill="test_skill",
        operation="delete_files", # Matches a rule
        parameters={}
    )
    action_manager.assign_permission_scope(action)
    assert action_manager.requires_confirmation(action) is True

def test_no_confirmation_needed(action_manager, mock_config_paths):
    Config.CONFIRMATION_RULES["confirmation_required"] = ["DELETE_FILES"]
    action = Action(
        action_id="123",
        skill="test_skill",
        operation="read_file", # Does not match any rule, not explicit
        parameters={}
    )
    action_manager.assign_permission_scope(action)
    assert action_manager.requires_confirmation(action) is False


# --- Test Sensitive Value Redaction ---
def test_redact_sensitive_values(action_manager):
    original_params = {
        "command": "sudo rm -rf /",
        "password": "mysecretpassword",
        "api_key": "someapikey123",
        "email": "testuser@example.com",
        "target": "C:/Users/SecretFolder",
        "body": "This is a very long email body that contains sensitive details that should be truncated when logged for audit purposes. This is more than 100 characters and should definitely be handled."
    }
    redacted_params = action_manager._redact_sensitive_values(original_params)

    assert redacted_params["command"] == "sudo rm -rf /"
    assert redacted_params["password"] == "[REDACTED]"
    assert redacted_params["api_key"] == "[REDACTED]"
    assert redacted_params["email"] == "***@example.com"
    assert "SecretFolder" in redacted_params["target"]
    assert redacted_params["body"] == "[REDACTED CONTENT]"
    assert len(redacted_params["body"]) < len(original_params["body"])


def test_redact_text_masks_standalone_bearer_authorization():
    redacted = ActionManager._redact_text(
        "provider failed with Authorization: Bearer secret-token-value"
    )

    assert "secret-token-value" not in redacted
    assert "[REDACTED]" in redacted


# --- Test Audit Logging ---
def test_audit_log_entry(action_manager, tmp_path):
    Config.AUDIT_LOG_FILE = tmp_path / "audit_log.json"
    action = Action(
        action_id="log_test_id",
        skill="audit_test",
        operation="log_operation",
        parameters={'data': 'sensitive_info'},
        permission_scope="SAFE_WRITE",
        risk_level="low"
    )
    action_manager.audit_log(action, "success", "Action completed")

    assert Config.AUDIT_LOG_FILE.exists()
    with open(Config.AUDIT_LOG_FILE, "r", encoding="utf-8") as f:
        log_entry = json.loads(f.readline())

    assert log_entry["action_id"] == "log_test_id"
    assert log_entry["outcome"] == "success"
    assert log_entry["parameters"]['data'] == "sensitive_info" # Not redacted if not in sensitive list
    assert "timestamp" in log_entry

def test_audit_log_redaction(action_manager, tmp_path):
    Config.AUDIT_LOG_FILE = tmp_path / "audit_log_redact.json"
    action = Action(
        action_id="log_redact_id",
        skill="audit_test",
        operation="log_secret",
        parameters={'password': 'supersecret'},
        permission_scope="SAFE_WRITE",
        risk_level="high"
    )
    action_manager.audit_log(action, "failed", "Auth failed")

    assert Config.AUDIT_LOG_FILE.exists()
    with open(Config.AUDIT_LOG_FILE, "r", encoding="utf-8") as f:
        log_entry = json.loads(f.readline())

    assert log_entry["parameters"]['password'] == "[REDACTED]"


# --- Test execute_action end-to-end (basic flow) ---
def test_execute_action_no_confirmation(action_manager, mock_controller):
    action_manager._execute_registered = Mock(return_value="Opening Downloads.")
    action = Action(
        action_id="exec_1",
        skill="windows",
        operation="open_folder",
        parameters={"folder": "Downloads"},
        risk_level="low",
        requires_confirmation=False
    )
    result = action_manager.execute_action(action)
    assert result == "Opening Downloads."
    mock_controller.agent.confirm.assert_not_called()

def test_execute_action_with_confirmation_approved(action_manager, mock_controller):
    # Mock the agent to return True for confirmation
    mock_controller.agent.confirm.return_value = True
    action_manager._execute_registered = Mock(return_value="Closed owned resources.")
    action = Action(
        action_id="exec_2",
        skill="windows",
        operation="close_all_jarvis_items",
        parameters={},
        risk_level="critical",
        requires_confirmation=True
    )
    result = action_manager.execute_action(action)
    assert result == "Closed owned resources."
    mock_controller.agent.confirm.assert_called_once_with(action)
    mock_controller.speak.assert_any_call("Sir, I need confirmation to close_all_jarvis_items.")

def test_execute_action_with_confirmation_denied(action_manager, mock_controller):
    # Mock the agent to return False for confirmation
    mock_controller.agent.confirm.return_value = False
    action_manager._execute_registered = Mock(side_effect=AssertionError("denied action ran"))
    action = Action(
        action_id="exec_3",
        skill="windows",
        operation="close_all_jarvis_items",
        parameters={},
        risk_level="critical",
        requires_confirmation=True
    )
    result = action_manager.execute_action(action)
    assert result == "Action denied by user."
    mock_controller.agent.confirm.assert_called_once_with(action)
    mock_controller.speak.assert_any_call("Action denied, sir.")

def test_execute_action_unknown_skill_rejection(action_manager, mock_controller):
    action = Action(
        action_id="exec_4",
        skill="unregistered_skill", # This will be rejected by the allowlist placeholder
        operation="do_something",
        parameters={},
        risk_level="low"
    )
    with pytest.raises(ValueError, match="Unknown skill: unregistered_skill"):
        action_manager.execute_action(action)    


def test_hermes_research_tool_uses_registered_jarvis_executor(
    action_manager, mock_controller, monkeypatch,
):
    observed = {}
    monkeypatch.setattr(
        "skills.research.search_web",
        lambda query, limit=6: observed.update(query=query, limit=limit) or [
            {"title": "Verified result", "url": "https://example.test"},
        ],
    )
    action = Action(
        action_id="hermes-step-1", skill="research", operation="search_web",
        parameters={"query": "renewable energy", "limit": 3},
        permission_scope="BROWSER_NAVIGATE", risk_level="low",
        requires_confirmation=False, reversible=True,
    )

    result = action_manager.execute_action(action)

    assert result == [{"title": "Verified result", "url": "https://example.test"}]
    assert observed == {"query": "renewable energy", "limit": 3}
    mock_controller.agent.confirm.assert_not_called()
