"""Prompt registry exceptions."""

class PromptError(Exception):
    pass

class TemplateNotFoundError(PromptError):
    pass

class MissingContextError(PromptError):
    pass