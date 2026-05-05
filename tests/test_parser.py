import base64
import pytest
from unittest.mock import patch, MagicMock

import modules.parser as parser_module
from modules.parser import parse_reply

GOAL = "Find the partnerships decision-maker and their direct contact email"
EMAIL = "contact@testorg.com"
SENT_ID = "sent_abc123"
REPLY_ID = "reply_xyz789"
REPLY_TEXT = "Hi, our partnerships lead is Maria Santos. You can reach her at maria@habitat.org.ph"

ALL_FOUND = [
    {"field": "partnerships decision-maker", "value": "Maria Santos", "found": True},
    {"field": "direct contact email", "value": "maria@habitat.org.ph", "found": True},
]
SOME_FOUND = [
    {"field": "partnerships decision-maker", "value": "Maria Santos", "found": True},
    {"field": "direct contact email", "value": None, "found": False},
]
NONE_FOUND = [
    {"field": "partnerships decision-maker", "value": None, "found": False},
    {"field": "direct contact email", "value": None, "found": False},
]


def _encoded(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


def _plain_message(message_id: str, body: str) -> dict:
    return {
        "id": message_id,
        "payload": {
            "mimeType": "text/plain",
            "body": {"data": _encoded(body)},
            "parts": [],
        },
    }


def _multipart_message(message_id: str, plain: str, html: str = "<p>html</p>") -> dict:
    return {
        "id": message_id,
        "payload": {
            "mimeType": "multipart/alternative",
            "body": {},
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": _encoded(plain)},
                    "parts": [],
                },
                {
                    "mimeType": "text/html",
                    "body": {"data": _encoded(html)},
                    "parts": [],
                },
            ],
        },
    }


def _mock_service_for_full_fetch(message_id: str, message: dict) -> MagicMock:
    svc = MagicMock()
    svc.users().messages().get(
        userId="me", id=message_id, format="full"
    ).execute.return_value = message
    return svc


# ---------------------------------------------------------------------------
# parse_reply — happy paths
# ---------------------------------------------------------------------------

def test_parse_reply_returns_none_when_no_reply():
    svc = MagicMock()
    with patch.object(parser_module, "_get_gmail_service", return_value=svc), \
         patch.object(parser_module, "_find_reply", return_value=None):
        result = parse_reply("test_org", EMAIL, GOAL, [SENT_ID])
    assert result is None


def test_parse_reply_high_confidence_all_fields_found():
    svc = _mock_service_for_full_fetch(REPLY_ID, _plain_message(REPLY_ID, REPLY_TEXT))
    groq_out = {"collected": ALL_FOUND, "confidence": "high"}

    with patch.object(parser_module, "_get_gmail_service", return_value=svc), \
         patch.object(parser_module, "_find_reply", return_value=REPLY_ID), \
         patch.object(parser_module, "_call_groq", return_value=groq_out):
        result = parse_reply("test_org", EMAIL, GOAL, [SENT_ID])

    assert result is not None
    assert result["confidence"] == "high"
    assert result["collected"] == ALL_FOUND
    assert all(item["found"] for item in result["collected"])


def test_parse_reply_includes_raw_reply_from_extracted_body():
    svc = _mock_service_for_full_fetch(REPLY_ID, _plain_message(REPLY_ID, REPLY_TEXT))
    groq_out = {"collected": ALL_FOUND, "confidence": "high"}

    with patch.object(parser_module, "_get_gmail_service", return_value=svc), \
         patch.object(parser_module, "_find_reply", return_value=REPLY_ID), \
         patch.object(parser_module, "_call_groq", return_value=groq_out):
        result = parse_reply("test_org", EMAIL, GOAL, [SENT_ID])

    assert result["raw_reply"] == REPLY_TEXT


def test_parse_reply_medium_confidence_when_some_fields_found():
    svc = _mock_service_for_full_fetch(REPLY_ID, _plain_message(REPLY_ID, "Maria Santos is our lead."))
    groq_out = {"collected": SOME_FOUND, "confidence": "medium"}

    with patch.object(parser_module, "_get_gmail_service", return_value=svc), \
         patch.object(parser_module, "_find_reply", return_value=REPLY_ID), \
         patch.object(parser_module, "_call_groq", return_value=groq_out):
        result = parse_reply("test_org", EMAIL, GOAL, [SENT_ID])

    assert result["confidence"] == "medium"
    found = [item["found"] for item in result["collected"]]
    assert True in found and False in found


def test_parse_reply_low_confidence_when_no_fields_found():
    svc = _mock_service_for_full_fetch(REPLY_ID, _plain_message(REPLY_ID, "Thanks for your email."))
    groq_out = {"collected": NONE_FOUND, "confidence": "low"}

    with patch.object(parser_module, "_get_gmail_service", return_value=svc), \
         patch.object(parser_module, "_find_reply", return_value=REPLY_ID), \
         patch.object(parser_module, "_call_groq", return_value=groq_out):
        result = parse_reply("test_org", EMAIL, GOAL, [SENT_ID])

    assert result["confidence"] == "low"
    assert not any(item["found"] for item in result["collected"])


# ---------------------------------------------------------------------------
# parse_reply — error handling
# ---------------------------------------------------------------------------

def test_parse_reply_exits_on_gmail_service_failure():
    with patch.object(parser_module, "_get_gmail_service", side_effect=Exception("auth failed")):
        with pytest.raises(SystemExit):
            parse_reply("test_org", EMAIL, GOAL, [SENT_ID])


def test_parse_reply_exits_when_groq_call_raises_system_exit():
    svc = _mock_service_for_full_fetch(REPLY_ID, _plain_message(REPLY_ID, REPLY_TEXT))
    with patch.object(parser_module, "_get_gmail_service", return_value=svc), \
         patch.object(parser_module, "_find_reply", return_value=REPLY_ID), \
         patch.object(parser_module, "_call_groq", side_effect=SystemExit("Groq failed")):
        with pytest.raises(SystemExit):
            parse_reply("test_org", EMAIL, GOAL, [SENT_ID])


# ---------------------------------------------------------------------------
# _find_reply — unit tests
# ---------------------------------------------------------------------------

def _messages_get_side_effect(id_to_thread: dict):
    def _get(**kwargs):
        mock = MagicMock()
        msg_id = kwargs.get("id")
        mock.execute.return_value = {"id": msg_id, "threadId": id_to_thread.get(msg_id, "")}
        return mock
    return _get


def test_find_reply_returns_message_id_when_reply_in_thread():
    svc = MagicMock()
    svc.users().messages().get.side_effect = _messages_get_side_effect(
        {SENT_ID: "thread001", REPLY_ID: "thread001"}
    )
    svc.users().messages().list(
        userId="me", q=f"from:{EMAIL}"
    ).execute.return_value = {"messages": [{"id": REPLY_ID}]}

    result = parser_module._find_reply(svc, EMAIL, [SENT_ID])
    assert result == REPLY_ID


def test_find_reply_returns_none_when_no_message_from_email():
    svc = MagicMock()
    svc.users().messages().get.side_effect = _messages_get_side_effect(
        {SENT_ID: "thread001"}
    )
    svc.users().messages().list(
        userId="me", q=f"from:{EMAIL}"
    ).execute.return_value = {"messages": []}

    result = parser_module._find_reply(svc, EMAIL, [SENT_ID])
    assert result is None


def test_find_reply_checks_all_sent_ids_before_giving_up():
    other_id = "other_sent_456"
    svc = MagicMock()
    svc.users().messages().get.side_effect = _messages_get_side_effect(
        {SENT_ID: "thread001", other_id: "thread002", REPLY_ID: "thread002"}
    )
    # search returns one candidate (REPLY_ID) which is in thread002, not thread001
    svc.users().messages().list(
        userId="me", q=f"from:{EMAIL}"
    ).execute.return_value = {"messages": [{"id": REPLY_ID}]}

    result = parser_module._find_reply(svc, EMAIL, [SENT_ID, other_id])
    assert result == REPLY_ID


# ---------------------------------------------------------------------------
# _extract_body — unit tests
# ---------------------------------------------------------------------------

def test_extract_body_from_simple_text_plain():
    msg = _plain_message("m1", "Hello from a plain message")
    assert parser_module._extract_body(msg) == "Hello from a plain message"


def test_extract_body_from_multipart_picks_plain_over_html():
    msg = _multipart_message("m1", "Plain text part", "<p>HTML part</p>")
    assert parser_module._extract_body(msg) == "Plain text part"


def test_extract_body_returns_empty_string_when_no_text_part():
    msg = {
        "id": "m1",
        "payload": {
            "mimeType": "multipart/mixed",
            "body": {},
            "parts": [
                {"mimeType": "application/pdf", "body": {"data": _encoded("binary")}, "parts": []},
            ],
        },
    }
    assert parser_module._extract_body(msg) == ""


def test_extract_body_handles_nested_multipart():
    inner_plain = {
        "mimeType": "text/plain",
        "body": {"data": _encoded("Nested plain text")},
        "parts": [],
    }
    msg = {
        "id": "m1",
        "payload": {
            "mimeType": "multipart/mixed",
            "body": {},
            "parts": [
                {
                    "mimeType": "multipart/alternative",
                    "body": {},
                    "parts": [inner_plain],
                }
            ],
        },
    }
    assert parser_module._extract_body(msg) == "Nested plain text"
