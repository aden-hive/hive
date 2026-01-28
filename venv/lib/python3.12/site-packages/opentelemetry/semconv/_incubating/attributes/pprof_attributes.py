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

PPROF_LOCATION_IS_FOLDED: Final = "pprof.location.is_folded"
"""
Provides an indication that multiple symbols map to this location's address, for example due to identical code folding by the linker. In that case the line information represents one of the multiple symbols. This field must be recomputed when the symbolization state of the profile changes.
"""

PPROF_MAPPING_HAS_FILENAMES: Final = "pprof.mapping.has_filenames"
"""
Indicates that there are filenames related to this mapping.
"""

PPROF_MAPPING_HAS_FUNCTIONS: Final = "pprof.mapping.has_functions"
"""
Indicates that there are functions related to this mapping.
"""

PPROF_MAPPING_HAS_INLINE_FRAMES: Final = "pprof.mapping.has_inline_frames"
"""
Indicates that there are inline frames related to this mapping.
"""

PPROF_MAPPING_HAS_LINE_NUMBERS: Final = "pprof.mapping.has_line_numbers"
"""
Indicates that there are line numbers related to this mapping.
"""

PPROF_PROFILE_COMMENT: Final = "pprof.profile.comment"
"""
Free-form text associated with the profile. This field should not be used to store any machine-readable information, it is only for human-friendly content.
"""
