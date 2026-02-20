"""
Credential Tester — verify synced credentials via live API calls.

Interactive agent that lists connected accounts, lets the user pick one,
loads the provider's tools, and runs a chat session to test the credential.
"""

from .agent import CredentialTesterAgent, edges, goal, nodes

__version__ = "1.0.0"

__all__ = [
    "CredentialTesterAgent",
    "goal",
    "nodes",
    "edges",
]
