# Copyright The OpenTelemetry Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import threading
import typing

from typing_extensions import deprecated

from opentelemetry.sdk._logs import ReadableLogRecord
from opentelemetry.sdk._logs.export import (
    LogRecordExporter,
    LogRecordExportResult,
)


class InMemoryLogRecordExporter(LogRecordExporter):
    """Implementation of :class:`.LogRecordExporter` that stores logs in memory.

    This class can be used for testing purposes. It stores the exported logs
    in a list in memory that can be retrieved using the
    :func:`.get_finished_logs` method.
    """

    def __init__(self):
        self._logs = []
        self._lock = threading.Lock()
        self._stopped = False

    def clear(self) -> None:
        with self._lock:
            self._logs.clear()

    def get_finished_logs(self) -> typing.Tuple[ReadableLogRecord, ...]:
        with self._lock:
            return tuple(self._logs)

    def export(
        self, batch: typing.Sequence[ReadableLogRecord]
    ) -> LogRecordExportResult:
        if self._stopped:
            return LogRecordExportResult.FAILURE
        with self._lock:
            self._logs.extend(batch)
        return LogRecordExportResult.SUCCESS

    def shutdown(self) -> None:
        self._stopped = True


@deprecated(
    "Use InMemoryLogRecordExporter. Since logs are not stable yet this WILL be removed in future releases."
)
class InMemoryLogExporter(InMemoryLogRecordExporter):
    pass
