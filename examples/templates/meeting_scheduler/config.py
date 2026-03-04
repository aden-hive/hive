"""Runtime configuration."""

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Meeting Scheduler"
    version: str = "1.0.0"
    description: str = (
        "Schedule meetings by checking Google Calendar availability, booking "
        "optimal time slots, recording details in Google Sheets, and sending "
        "email confirmations with Google Meet links to attendees."
    )
    intro_message: str = (
        "Hi! I'm your meeting scheduler. Tell me who you'd like to meet with, "
        "how long the meeting should be, and what it's about — I'll check "
        "calendar availability, book a time slot, log it to your spreadsheet, "
        "and send a confirmation email with a Google Meet link. "
        "Who would you like to schedule a meeting with?"
    )


metadata = AgentMetadata()
