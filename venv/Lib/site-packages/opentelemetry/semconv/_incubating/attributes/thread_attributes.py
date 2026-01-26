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

from typing import Final

THREAD_ID: Final = "thread.id"
"""
Current "managed" thread ID (as opposed to OS thread ID).
Note: Examples of where the value can be extracted from:

| Language or platform  | Source |
| --- | --- |
| JVM | `Thread.currentThread().threadId()` |
| .NET | `Thread.CurrentThread.ManagedThreadId` |
| Python | `threading.current_thread().ident` |
| Ruby | `Thread.current.object_id` |
| C++ | `std::this_thread::get_id()` |
| Erlang | `erlang:self()` |.
"""

THREAD_NAME: Final = "thread.name"
"""
Current thread name.
Note: Examples of where the value can be extracted from:

| Language or platform  | Source |
| --- | --- |
| JVM | `Thread.currentThread().getName()` |
| .NET | `Thread.CurrentThread.Name` |
| Python | `threading.current_thread().name` |
| Ruby | `Thread.current.name` |
| Erlang | `erlang:process_info(self(), registered_name)` |.
"""
