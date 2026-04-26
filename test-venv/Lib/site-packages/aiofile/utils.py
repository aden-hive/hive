import asyncio
import collections.abc
import io
import os
from abc import ABC, abstractmethod
from pathlib import Path
from types import MappingProxyType
from typing import Any, Generator, Tuple, Union

from .aio import AIOFile, FileIOType


ENCODING_MAP = MappingProxyType({
    "utf-8": 4,
    "utf-16": 8,
    "UTF-8": 4,
    "UTF-16": 8,
})


async def unicode_reader(
    afp: AIOFile, chunk_size: int, offset: int, encoding: str = "utf-8",
) -> Tuple[int, str]:

    if chunk_size < 0:
        chunk_bytes = await afp.read_bytes(-1, offset)
        return len(chunk_bytes), chunk_bytes.decode(encoding=encoding)

    last_error = None
    for retry in range(ENCODING_MAP.get(encoding, 4)):
        chunk_bytes = await afp.read_bytes(chunk_size + retry, offset)
        try:
            chunk = chunk_bytes.decode(encoding=encoding)
            break
        except UnicodeDecodeError as e:
            last_error = e
    else:
        raise last_error    # type: ignore

    chunk_size = len(chunk_bytes)

    return chunk_size, chunk


class Reader(collections.abc.AsyncIterable):
    __slots__ = "_chunk_size", "__offset", "file", "__lock", "encoding"

    CHUNK_SIZE = 32 * 1024

    def __init__(
        self, aio_file: AIOFile, offset: int = 0,
        chunk_size: int = CHUNK_SIZE,
    ):

        self.__lock = asyncio.Lock()
        self.__offset = int(offset)

        self._chunk_size = int(chunk_size)
        self.file = aio_file
        self.encoding = self.file.encoding

    async def read_chunk(self) -> Union[str, bytes]:
        async with self.__lock:
            if self.file.mode.binary:
                chunk = await self.file.read_bytes(
                    self._chunk_size, self.__offset,
                )   # type: Union[str, bytes]
                chunk_size = len(chunk)
            else:
                chunk_size, chunk = await unicode_reader(
                    self.file, self._chunk_size, self.__offset,
                    encoding=self.encoding,
                )
        self.__offset += chunk_size
        return chunk

    async def __anext__(self) -> Union[str, bytes]:
        chunk = await self.read_chunk()

        if not chunk:
            raise StopAsyncIteration(chunk)

        return chunk

    def __aiter__(self) -> "Reader":
        return self


class Writer:
    __slots__ = "__chunk_size", "__offset", "__aio_file", "__lock"

    def __init__(self, aio_file: AIOFile, offset: int = 0):
        self.__offset = int(offset)
        self.__aio_file = aio_file
        self.__lock = asyncio.Lock()

    async def __call__(self, data: Union[str, bytes]) -> None:
        async with self.__lock:
            if isinstance(data, str):
                data = self.__aio_file.encode_bytes(data)

            await self.__aio_file.write_bytes(data, self.__offset)
            self.__offset += len(data)


class LineReader(collections.abc.AsyncIterable):
    CHUNK_SIZE = 4192

    def __init__(
        self, aio_file: AIOFile, offset: int = 0,
        chunk_size: int = CHUNK_SIZE, line_sep: str = "\n",
    ):
        self.__reader = Reader(aio_file, chunk_size=chunk_size, offset=offset)

        self._buffer = (
            io.BytesIO() if aio_file.mode.binary else io.StringIO()
        )   # type: Any

        self.linesep = (
            aio_file.encode_bytes(line_sep)
            if aio_file.mode.binary
            else line_sep
        )

    async def readline(self) -> Union[str, bytes]:
        while True:
            line = self._buffer.readline()
            if line and line.endswith(self.linesep):
                return line

            buffer_remainder = line + self._buffer.read()
            self._buffer.truncate(0)
            self._buffer.seek(0)

            # No line in buffer, read more data
            chunk = await self.__reader.read_chunk()
            if not chunk:
                # No more data to read, return any remaining content in the buffer
                return buffer_remainder
            # We have more data to read, write it to the buffer and handle it in the next iteration
            self._buffer.write(buffer_remainder)
            self._buffer.write(chunk)
            self._buffer.seek(0)

    async def __anext__(self) -> Union[bytes, str]:
        line = await self.readline()

        if not line:
            # We are finished, close the buffer and raise StopAsyncIteration
            self._buffer.close()
            raise StopAsyncIteration(line)

        return line

    def __aiter__(self) -> "LineReader":
        return self


class FileIOWrapperBase(ABC):
    _READLINE_CHUNK_SIZE = 4192

    def __init__(self, afp: AIOFile, *, offset: int = 0):
        self._offset = offset
        self._lock = asyncio.Lock()
        self.file = afp

        if self.file.mode.appending:
            try:
                self._offset = os.stat(afp.name).st_size
            except FileNotFoundError:
                self._offset = 0

    @abstractmethod
    async def read(self, length: int = -1) -> Any:
        raise NotImplementedError

    @abstractmethod
    async def write(self, data: Any) -> int:
        raise NotImplementedError

    @abstractmethod
    async def readline(
        self, size: int = -1, newline: Any = ...,
    ) -> Union[str, bytes]:
        raise NotImplementedError

    def seek(self, offset: int) -> None:
        self._offset = offset

    def tell(self) -> int:
        return self._offset

    async def flush(self, sync_metadata: bool = False) -> None:
        if sync_metadata:
            await self.file.fsync()
        else:
            await self.file.fdsync()

    async def close(self) -> None:
        await self.file.close()

    def __await__(self) -> Generator[None, None, "FileIOWrapperBase"]:
        yield from self.file.__await__()
        return self

    async def __aenter__(self) -> "FileIOWrapperBase":
        await self.file.open()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    def __aiter__(self) -> LineReader:
        return LineReader(self.file)

    def iter_chunked(self, chunk_size: int = Reader.CHUNK_SIZE) -> Reader:
        return Reader(self.file, chunk_size=chunk_size, offset=self._offset)


class BinaryFileWrapper(FileIOWrapperBase):
    def __init__(self, afp: AIOFile):
        if not afp.mode.binary:
            raise ValueError("Expected file in binary mode")
        super().__init__(afp)

    async def __read(self, length: int) -> bytes:
        data = await self.file.read_bytes(length, self._offset)
        self._offset += len(data)
        return data

    async def read(self, length: int = -1) -> bytes:
        async with self._lock:
            return await self.__read(length)

    async def write(self, data: bytes) -> int:
        async with self._lock:
            operation = self.file.write_bytes(data, self._offset)
            self._offset += len(data)
        await operation
        return len(data)

    async def readline(self, size: int = -1, newline: bytes = b"\n") -> bytes:
        async with self._lock:
            offset = self._offset
            with io.BytesIO() as fp:
                while True:
                    chunk = await self.__read(self._READLINE_CHUNK_SIZE)

                    if chunk:
                        if newline not in chunk:
                            fp.write(chunk)
                            continue

                        fp.write(chunk)

                    if 0 < size <= fp.tell():
                        fp.seek(size)
                        fp.truncate(size)
                        return fp.getvalue()

                    fp.seek(0)
                    line = fp.readline()
                    self._offset = offset + fp.tell()
                    return line


class TextFileWrapper(FileIOWrapperBase):
    def __init__(self, afp: AIOFile):
        if afp.mode.binary:
            raise ValueError("Expected file in text mode")
        super().__init__(afp)
        self.encoding = self.file.encoding

    async def __read(self, length: int) -> str:
        chunk_size = 0
        offset = self._offset
        chunk = ""
        while length < 0 or length > len(chunk):
            part_offset, part = await unicode_reader(
                self.file, length, offset, self.encoding,
            )

            if not part:
                break

            chunk += part
            offset += part_offset

        if chunk_size > length > 0:
            chunk = chunk[:length]
            offset = length

        self._offset = offset
        return chunk

    async def read(self, length: int = -1) -> str:
        async with self._lock:
            return await self.__read(length)

    async def write(self, data: str) -> int:
        async with self._lock:
            data_bytes = data.encode(self.encoding)
            operation = self.file.write_bytes(data_bytes, self._offset)
            self._offset += len(data_bytes)

        await operation
        return len(data_bytes)

    async def readline(self, size: int = -1, newline: str = "\n") -> str:
        async with self._lock:
            offset = self._offset
            with io.StringIO() as fp:
                while True:
                    chunk = await self.__read(self._READLINE_CHUNK_SIZE)

                    if chunk:
                        if newline not in chunk:
                            fp.write(chunk)
                            continue

                        fp.write(chunk)

                    if 0 < size <= fp.tell():
                        fp.seek(size)
                        fp.truncate(size)
                        return fp.getvalue()

                    fp.seek(0)
                    line = fp.readline()
                    self._offset = offset + len(
                        line.encode(encoding=self.encoding),
                    )
                    return line


def async_open(
    file_specifier: Union[str, Path, FileIOType],
    mode: str = "r", *args: Any, **kwargs: Any,
) -> Union[BinaryFileWrapper, TextFileWrapper]:
    if isinstance(file_specifier, (str, Path)):
        afp = AIOFile(str(file_specifier), mode, *args, **kwargs)
    else:
        if args:
            raise ValueError("Arguments denied when IO[Any] opening.")
        afp = AIOFile.from_fp(file_specifier, **kwargs)

    if not afp.mode.binary:
        return TextFileWrapper(afp)

    return BinaryFileWrapper(afp)


__all__ = (
    "BinaryFileWrapper",
    "FileIOWrapperBase",
    "LineReader",
    "Reader",
    "TextFileWrapper",
    "Writer",
    "async_open",
    "unicode_reader",
)
