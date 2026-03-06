"""Tests for the normalized email tool schemas."""

from pydantic import ValidationError
import pytest

from aden_tools.tools.email_tool.schemas import (
    EmailAddress,
    EmailSendRequest,
    EmailMessageSummary,
)


class TestEmailAddress:
    def test_valid_email_address(self):
        obj = EmailAddress(email="test@example.com", name="Test User")
        assert obj.email == "test@example.com"
        assert obj.name == "Test User"

    def test_missing_email_fails(self):
        with pytest.raises(ValidationError):
            EmailAddress(name="Test User")


class TestEmailSendRequest:
    def test_default_provider_is_auto(self):
        req = EmailSendRequest(
            to=["user@example.com"],
            subject="Test Subject",
            body_text="Hello Context",
        )
        assert req.provider == "auto"

    def test_accepts_specific_provider(self):
        req = EmailSendRequest(
            to=["user@example.com"],
            subject="Test Subject",
            body_text="Hello Context",
            provider="mock",
        )
        assert req.provider == "mock"

    def test_requires_to_and_subject(self):
        with pytest.raises(ValidationError):
            EmailSendRequest(to=["user@example.com"])  # missing subject
        
        with pytest.raises(ValidationError):
            EmailSendRequest(subject="Test")  # missing to
