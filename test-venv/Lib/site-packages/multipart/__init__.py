# Copyright 2012, Andrew Dunham
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# This only works if using a file system, other loaders not implemented.

import importlib.util
import sys
import warnings
from pathlib import Path

for p in sys.path:
    file_path = Path(p, "multipart.py")
    try:
        if file_path.is_file():
            spec = importlib.util.spec_from_file_location("multipart", file_path)
            assert spec is not None, f"{file_path} found but not loadable!"
            module = importlib.util.module_from_spec(spec)
            sys.modules["multipart"] = module
            assert spec.loader is not None, f"{file_path} must be loadable!"
            spec.loader.exec_module(module)
            break
    except PermissionError:
        pass
else:
    warnings.warn("Please use `import python_multipart` instead.", PendingDeprecationWarning, stacklevel=2)
    from python_multipart import *
    from python_multipart import __all__, __version__
