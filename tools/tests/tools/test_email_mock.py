"""Tests for the Mock Email Provider."""

from datetime import datetime, timezone
import pytest

from aden_tools.tools.email_tool.providers.mock import MockEmailProvider
from aden_tools.tools.email_tool.schemas import (
    EmailListRequest,
    EmailReadRequest,
    EmailSearchRequest,
    EmailSendRequest,
)

@pytest.fixture
def provider():
    # The mock provider automatically seeds one email
    return MockEmailProvider()

class TestMockEmailProvider:

    def test_provider_id(self, provider):
        assert provider.provider_id == "mock"

    def test_list_emails_returns_seed_data(self, provider):
        req = EmailListRequest(provider="mock")
        res = provider.list_emails(req)
        assert len(res.messages) == 1
        assert res.messages[0].subject == "Welcome to Hive"
        assert res.messages[0].unread is True

    def test_read_email_success(self, provider):
        # Grab ID from seed list
        req_list = EmailListRequest(provider="mock")
        res_list = provider.list_emails(req_list)
        msg_id = res_list.messages[0].message_id

        req_read = EmailReadRequest(message_id=msg_id, provider="mock")
        res_read = provider.read_email(req_read)
        
        assert res_read.message is not None
        assert res_read.message.body_text is not None
        assert res_read.message.body_html is not None

    def test_read_email_no_html_requested(self, provider):
        req_list = EmailListRequest(provider="mock")
        res_list = provider.list_emails(req_list)
        msg_id = res_list.messages[0].message_id

        req_read = EmailReadRequest(message_id=msg_id, include_body_html=False, provider="mock")
        res_read = provider.read_email(req_read)
        
        assert res_read.message is not None
        assert res_read.message.body_text is not None
        assert res_read.message.body_html is None

    def test_read_email_not_found(self, provider):
        req = EmailReadRequest(message_id="does_not_exist", provider="mock")
        res = provider.read_email(req)
        
        assert res.message is None
        assert "not found" in res.error

    def test_send_email_adds_to_store(self, provider):
        req = EmailSendRequest(
            to=["recipient@test.com"],
            subject="Integration Test",
            body_text="Testing the mock",
            from_email="sender@test.com",
            provider="mock"
        )
        
        res_send = provider.send_email(req)
        assert res_send.success is True
        assert res_send.message_id is not None
        
        # Verify it shows up in "sent" folder
        res_list = provider.list_emails(EmailListRequest(folder="sent", provider="mock"))
        assert len(res_list.messages) == 1
        assert res_list.messages[0].subject == "Integration Test"
        assert res_list.messages[0].unread is False

    def test_search_emails_by_query(self, provider):
        req_send = EmailSendRequest(
            to=["recipient@test.com"],
            subject="Unique Searchable Subject 123",
            body_text="Text body",
            provider="mock"
        )
        provider.send_email(req_send)
        
        req_search = EmailSearchRequest(query="Unique Searchable", provider="mock")
        res_search = provider.search_emails(req_search)
        
        assert len(res_search.messages) == 1
        assert res_search.messages[0].subject == "Unique Searchable Subject 123"

    def test_search_emails_unread_filter(self, provider):
        # We start with 1 unread seed message
        req1 = EmailSearchRequest(unread_only=True, provider="mock")
        res1 = provider.search_emails(req1)
        assert len(res1.messages) == 1
        
        req2 = EmailSearchRequest(unread_only=False, provider="mock")
        res2 = provider.search_emails(req2)
        assert len(res2.messages) == 0

    def test_list_folders(self, provider):
        folders = provider.list_folders()
        assert len(folders) == 4
        assert any(f.id == "inbox" for f in folders) 
