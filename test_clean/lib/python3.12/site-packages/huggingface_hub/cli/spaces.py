# Copyright 2026 The HuggingFace Team. All rights reserved.
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
"""Contains commands to interact with spaces on the Hugging Face Hub.

Usage:
    # list spaces on the Hub
    hf spaces ls

    # list spaces with a search query
    hf spaces ls --search "chatbot"

    # get info about a space
    hf spaces info enzostvs/deepsite
"""

import enum
import json
from typing import Annotated, Optional, get_args

import typer

from huggingface_hub.errors import RepositoryNotFoundError, RevisionNotFoundError
from huggingface_hub.hf_api import ExpandSpaceProperty_T, SpaceSort_T
from huggingface_hub.utils import ANSI

from ._cli_utils import (
    AuthorOpt,
    FilterOpt,
    LimitOpt,
    RevisionOpt,
    SearchOpt,
    TokenOpt,
    get_hf_api,
    make_expand_properties_parser,
    repo_info_to_dict,
    typer_factory,
)


_EXPAND_PROPERTIES = sorted(get_args(ExpandSpaceProperty_T))
_SORT_OPTIONS = get_args(SpaceSort_T)
SpaceSortEnum = enum.Enum("SpaceSortEnum", {s: s for s in _SORT_OPTIONS}, type=str)  # type: ignore[misc]


ExpandOpt = Annotated[
    Optional[str],
    typer.Option(
        help=f"Comma-separated properties to expand. Example: '--expand=likes,tags'. Valid: {', '.join(_EXPAND_PROPERTIES)}.",
        callback=make_expand_properties_parser(_EXPAND_PROPERTIES),
    ),
]


spaces_cli = typer_factory(help="Interact with spaces on the Hub.")


@spaces_cli.command("ls")
def spaces_ls(
    search: SearchOpt = None,
    author: AuthorOpt = None,
    filter: FilterOpt = None,
    sort: Annotated[
        Optional[SpaceSortEnum],
        typer.Option(help="Sort results."),
    ] = None,
    limit: LimitOpt = 10,
    expand: ExpandOpt = None,
    token: TokenOpt = None,
) -> None:
    """List spaces on the Hub."""
    api = get_hf_api(token=token)
    sort_key = sort.value if sort else None
    results = [
        repo_info_to_dict(space_info)
        for space_info in api.list_spaces(
            filter=filter, author=author, search=search, sort=sort_key, limit=limit, expand=expand
        )
    ]
    print(json.dumps(results, indent=2))


@spaces_cli.command("info")
def spaces_info(
    space_id: Annotated[str, typer.Argument(help="The space ID (e.g. `username/repo-name`).")],
    revision: RevisionOpt = None,
    expand: ExpandOpt = None,
    token: TokenOpt = None,
) -> None:
    """Get info about a space on the Hub."""
    api = get_hf_api(token=token)
    try:
        info = api.space_info(repo_id=space_id, revision=revision, expand=expand)  # type: ignore[arg-type]
    except RepositoryNotFoundError:
        print(f"Space {ANSI.bold(space_id)} not found.")
        raise typer.Exit(code=1)
    except RevisionNotFoundError:
        print(f"Revision {ANSI.bold(str(revision))} not found on {ANSI.bold(space_id)}.")
        raise typer.Exit(code=1)
    print(json.dumps(repo_info_to_dict(info), indent=2))
