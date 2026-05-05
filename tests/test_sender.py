import json
import pytest
from unittest.mock import patch, MagicMock

import modules.sender as sender_module
from modules.sender import send_email

SAMPLE_DRAFT = {
    "org": "Test Org",
    "to": "recipient@example.com",
    "subject": "Test Subject",
    "body": "Hello test body.",
    "goal": "test goal",
    "iteration": 1,
    "generated_at": "2026-05-05T00:00:00Z",
}


def test_send_email_returns_message_id_and_creates_sent_log(tmp_path):
    """Happy path: returns gmail_message_id and saves a 'sent' log file."""
    mock_service = MagicMock()
    mock_service.users().messages().send().execute.return_value = {"id": "abc123"}

    with patch.object(sender_module, "_get_gmail_service", return_value=mock_service), \
         patch.object(sender_module, "_base_dir", return_value=str(tmp_path)):
        result = send_email(SAMPLE_DRAFT)

    assert result == "abc123"

    sent_path = tmp_path / "data" / "sent" / "test_org_1.json"
    assert sent_path.exists(), "sent log file was not created"
    log = json.loads(sent_path.read_text())
    assert log["status"] == "sent"
    assert log["gmail_message_id"] == "abc123"
    assert log["org"] == "Test Org"
    assert log["to"] == "recipient@example.com"
    assert log["subject"] == "Test Subject"
    assert log["iteration"] == 1
    assert "sent_at" in log


def test_send_email_saves_failed_log_and_raises_when_send_errors(tmp_path):
    """Send call fails: saves 'failed' log with error message, then raises."""
    mock_service = MagicMock()
    mock_service.users().messages().send().execute.side_effect = Exception("quota exceeded")

    with patch.object(sender_module, "_get_gmail_service", return_value=mock_service), \
         patch.object(sender_module, "_base_dir", return_value=str(tmp_path)):
        with pytest.raises(Exception, match="quota exceeded"):
            send_email(SAMPLE_DRAFT)

    sent_path = tmp_path / "data" / "sent" / "test_org_1.json"
    assert sent_path.exists(), "failed log file was not created"
    log = json.loads(sent_path.read_text())
    assert log["status"] == "failed"
    assert "quota exceeded" in log["error"]


def test_send_email_saves_fallback_when_service_unavailable(tmp_path):
    """Auth/service build fails: saves fallback .txt and 'saved_locally' log, no exception."""
    with patch.object(sender_module, "_get_gmail_service", side_effect=Exception("no credentials")), \
         patch.object(sender_module, "_base_dir", return_value=str(tmp_path)):
        result = send_email(SAMPLE_DRAFT)

    fallback_path = tmp_path / "data" / "drafts" / "test_org_1_fallback.txt"
    assert fallback_path.exists(), "fallback .txt was not created"
    assert "Hello test body." in fallback_path.read_text()

    sent_path = tmp_path / "data" / "sent" / "test_org_1.json"
    assert sent_path.exists(), "saved_locally log was not created"
    log = json.loads(sent_path.read_text())
    assert log["status"] == "saved_locally"
    assert result is None
