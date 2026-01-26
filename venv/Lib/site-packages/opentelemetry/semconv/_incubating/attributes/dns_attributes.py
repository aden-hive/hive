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

DNS_ANSWERS: Final = "dns.answers"
"""
The list of IPv4 or IPv6 addresses resolved during DNS lookup.
"""

DNS_QUESTION_NAME: Final = "dns.question.name"
"""
The name being queried.
Note: The name represents the queried domain name as it appears in the DNS query without any additional normalization.
"""
