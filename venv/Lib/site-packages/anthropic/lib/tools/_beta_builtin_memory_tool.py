from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING, Any, cast
from typing_extensions import override, assert_never

from ..._models import construct_type_unchecked
from ...types.beta import (
    BetaMemoryTool20250818Param,
    BetaMemoryTool20250818Command,
    BetaCacheControlEphemeralParam,
    BetaMemoryTool20250818ViewCommand,
    BetaMemoryTool20250818CreateCommand,
    BetaMemoryTool20250818DeleteCommand,
    BetaMemoryTool20250818InsertCommand,
    BetaMemoryTool20250818RenameCommand,
    BetaMemoryTool20250818StrReplaceCommand,
)
from ._beta_functions import BetaBuiltinFunctionTool, BetaFunctionToolResultType, BetaAsyncBuiltinFunctionTool


class BetaAbstractMemoryTool(BetaBuiltinFunctionTool):
    """Abstract base class for memory tool implementations.

    This class provides the interface for implementing a custom memory backend for Claude.

    Subclass this to create your own memory storage solution (e.g., database, cloud storage, encrypted files, etc.).

    Example usage:

    ```py
    class MyMemoryTool(BetaAbstractMemoryTool):
        def view(self, command: BetaMemoryTool20250818ViewCommand) -> BetaFunctionToolResultType:
            ...
            return "view result"

        def create(self, command: BetaMemoryTool20250818CreateCommand) -> BetaFunctionToolResultType:
            ...
            return "created successfully"

        # ... implement other abstract methods


    client = Anthropic()
    memory_tool = MyMemoryTool()
    message = client.beta.messages.run_tools(
        model="claude-sonnet-4-5",
        messages=[{"role": "user", "content": "Remember that I like coffee"}],
        tools=[memory_tool],
    ).until_done()
    ```
    """

    def __init__(self, *, cache_control: BetaCacheControlEphemeralParam | None = None) -> None:
        super().__init__()
        self._cache_control = cache_control

    @override
    def to_dict(self) -> BetaMemoryTool20250818Param:
        param: BetaMemoryTool20250818Param = {"type": "memory_20250818", "name": "memory"}

        if self._cache_control is not None:
            param["cache_control"] = self._cache_control

        return param

    @override
    def call(self, input: object) -> BetaFunctionToolResultType:
        command = cast(
            BetaMemoryTool20250818Command,
            construct_type_unchecked(value=input, type_=cast(Any, BetaMemoryTool20250818Command)),
        )
        return self.execute(command)

    def execute(self, command: BetaMemoryTool20250818Command) -> BetaFunctionToolResultType:
        """Execute a memory command and return the result.

        This method dispatches to the appropriate handler method based on the
        command type (view, create, str_replace, insert, delete, rename).

        You typically don't need to override this method.
        """
        if command.command == "view":
            return self.view(command)
        elif command.command == "create":
            return self.create(command)
        elif command.command == "str_replace":
            return self.str_replace(command)
        elif command.command == "insert":
            return self.insert(command)
        elif command.command == "delete":
            return self.delete(command)
        elif command.command == "rename":
            return self.rename(command)
        elif TYPE_CHECKING:  # type: ignore[unreachable]
            assert_never(command)
        else:
            raise NotImplementedError(f"Unknown command: {command.command}")

    @abstractmethod
    def view(self, command: BetaMemoryTool20250818ViewCommand) -> BetaFunctionToolResultType:
        """View the contents of a memory path."""
        pass

    @abstractmethod
    def create(self, command: BetaMemoryTool20250818CreateCommand) -> BetaFunctionToolResultType:
        """Create a new memory file with the specified content."""
        pass

    @abstractmethod
    def str_replace(self, command: BetaMemoryTool20250818StrReplaceCommand) -> BetaFunctionToolResultType:
        """Replace text in a memory file."""
        pass

    @abstractmethod
    def insert(self, command: BetaMemoryTool20250818InsertCommand) -> BetaFunctionToolResultType:
        """Insert text at a specific line number in a memory file."""
        pass

    @abstractmethod
    def delete(self, command: BetaMemoryTool20250818DeleteCommand) -> BetaFunctionToolResultType:
        """Delete a memory file or directory."""
        pass

    @abstractmethod
    def rename(self, command: BetaMemoryTool20250818RenameCommand) -> BetaFunctionToolResultType:
        """Rename or move a memory file or directory."""
        pass

    def clear_all_memory(self) -> BetaFunctionToolResultType:
        """Clear all memory data."""
        raise NotImplementedError("clear_all_memory not implemented")


class BetaAsyncAbstractMemoryTool(BetaAsyncBuiltinFunctionTool):
    """Abstract base class for memory tool implementations.

    This class provides the interface for implementing a custom memory backend for Claude.

    Subclass this to create your own memory storage solution (e.g., database, cloud storage, encrypted files, etc.).

    Example usage:

    ```py
    class MyMemoryTool(BetaAbstractMemoryTool):
        def view(self, command: BetaMemoryTool20250818ViewCommand) -> BetaFunctionToolResultType:
            ...
            return "view result"

        def create(self, command: BetaMemoryTool20250818CreateCommand) -> BetaFunctionToolResultType:
            ...
            return "created successfully"

        # ... implement other abstract methods


    client = Anthropic()
    memory_tool = MyMemoryTool()
    message = client.beta.messages.run_tools(
        model="claude-3-5-sonnet-20241022",
        messages=[{"role": "user", "content": "Remember that I like coffee"}],
        tools=[memory_tool],
    ).until_done()
    ```
    """

    def __init__(self, *, cache_control: BetaCacheControlEphemeralParam | None = None) -> None:
        super().__init__()
        self._cache_control = cache_control

    @override
    def to_dict(self) -> BetaMemoryTool20250818Param:
        param: BetaMemoryTool20250818Param = {"type": "memory_20250818", "name": "memory"}

        if self._cache_control is not None:
            param["cache_control"] = self._cache_control

        return param

    @override
    async def call(self, input: object) -> BetaFunctionToolResultType:
        command = cast(
            BetaMemoryTool20250818Command,
            construct_type_unchecked(value=input, type_=cast(Any, BetaMemoryTool20250818Command)),
        )
        return await self.execute(command)

    async def execute(self, command: BetaMemoryTool20250818Command) -> BetaFunctionToolResultType:
        """Execute a memory command and return the result.

        This method dispatches to the appropriate handler method based on the
        command type (view, create, str_replace, insert, delete, rename).

        You typically don't need to override this method.
        """
        if command.command == "view":
            return await self.view(command)
        elif command.command == "create":
            return await self.create(command)
        elif command.command == "str_replace":
            return await self.str_replace(command)
        elif command.command == "insert":
            return await self.insert(command)
        elif command.command == "delete":
            return await self.delete(command)
        elif command.command == "rename":
            return await self.rename(command)
        elif TYPE_CHECKING:  # type: ignore[unreachable]
            assert_never(command)
        else:
            raise NotImplementedError(f"Unknown command: {command.command}")

    @abstractmethod
    async def view(self, command: BetaMemoryTool20250818ViewCommand) -> BetaFunctionToolResultType:
        """View the contents of a memory path."""
        pass

    @abstractmethod
    async def create(self, command: BetaMemoryTool20250818CreateCommand) -> BetaFunctionToolResultType:
        """Create a new memory file with the specified content."""
        pass

    @abstractmethod
    async def str_replace(self, command: BetaMemoryTool20250818StrReplaceCommand) -> BetaFunctionToolResultType:
        """Replace text in a memory file."""
        pass

    @abstractmethod
    async def insert(self, command: BetaMemoryTool20250818InsertCommand) -> BetaFunctionToolResultType:
        """Insert text at a specific line number in a memory file."""
        pass

    @abstractmethod
    async def delete(self, command: BetaMemoryTool20250818DeleteCommand) -> BetaFunctionToolResultType:
        """Delete a memory file or directory."""
        pass

    @abstractmethod
    async def rename(self, command: BetaMemoryTool20250818RenameCommand) -> BetaFunctionToolResultType:
        """Rename or move a memory file or directory."""
        pass

    async def clear_all_memory(self) -> BetaFunctionToolResultType:
        """Clear all memory data."""
        raise NotImplementedError("clear_all_memory not implemented")
