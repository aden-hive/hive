# Copyright 2022 The HuggingFace Team. All rights reserved.
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
"""Contains CLI utilities (styling, helpers)."""

import dataclasses
import datetime
import importlib.metadata
import os
import time
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal, Optional, Union

import click
import typer

from huggingface_hub import DatasetInfo, ModelInfo, SpaceInfo, __version__, constants
from huggingface_hub.utils import ANSI, get_session, hf_raise_for_status, installation_method, logging


logger = logging.get_logger()


if TYPE_CHECKING:
    from huggingface_hub.hf_api import HfApi


def get_hf_api(token: Optional[str] = None) -> "HfApi":
    # Import here to avoid circular import
    from huggingface_hub.hf_api import HfApi

    return HfApi(token=token, library_name="huggingface-cli", library_version=__version__)


#### TYPER UTILS


class AlphabeticalMixedGroup(typer.core.TyperGroup):
    """
    Typer Group that lists commands and sub-apps mixed and alphabetically.
    """

    def list_commands(self, ctx: click.Context) -> list[str]:  # type: ignore[name-defined]
        # click.Group stores both commands and subgroups in `self.commands`
        return sorted(self.commands.keys())


def typer_factory(help: str) -> typer.Typer:
    return typer.Typer(
        help=help,
        add_completion=True,
        no_args_is_help=True,
        cls=AlphabeticalMixedGroup,
        # Disable rich completely for consistent experience
        rich_markup_mode=None,
        rich_help_panel=None,
        pretty_exceptions_enable=False,
    )


class RepoType(str, Enum):
    model = "model"
    dataset = "dataset"
    space = "space"


RepoIdArg = Annotated[
    str,
    typer.Argument(
        help="The ID of the repo (e.g. `username/repo-name`).",
    ),
]


RepoTypeOpt = Annotated[
    RepoType,
    typer.Option(
        help="The type of repository (model, dataset, or space).",
    ),
]

TokenOpt = Annotated[
    Optional[str],
    typer.Option(
        help="A User Access Token generated from https://huggingface.co/settings/tokens.",
    ),
]

PrivateOpt = Annotated[
    Optional[bool],
    typer.Option(
        help="Whether to create a private repo if repo doesn't exist on the Hub. Ignored if the repo already exists.",
    ),
]

RevisionOpt = Annotated[
    Optional[str],
    typer.Option(
        help="Git revision id which can be a branch name, a tag, or a commit hash.",
    ),
]


LimitOpt = Annotated[
    int,
    typer.Option(help="Limit the number of results."),
]

AuthorOpt = Annotated[
    Optional[str],
    typer.Option(help="Filter by author or organization."),
]

FilterOpt = Annotated[
    Optional[list[str]],
    typer.Option(help="Filter by tags (e.g. 'text-classification'). Can be used multiple times."),
]

SearchOpt = Annotated[
    Optional[str],
    typer.Option(help="Search query."),
]


def repo_info_to_dict(info: Union[ModelInfo, DatasetInfo, SpaceInfo]) -> dict[str, object]:
    """Convert repo info dataclasses to json-serializable dicts."""
    return {
        k: v.isoformat() if isinstance(v, datetime.datetime) else v
        for k, v in dataclasses.asdict(info).items()
        if v is not None
    }


def make_expand_properties_parser(valid_properties: list[str]):
    """Create a callback to parse and validate comma-separated expand properties."""

    def _parse_expand_properties(value: Optional[str]) -> Optional[list[str]]:
        if value is None:
            return None
        properties = [p.strip() for p in value.split(",")]
        for prop in properties:
            if prop not in valid_properties:
                raise typer.BadParameter(
                    f"Invalid expand property: '{prop}'. Valid values are: {', '.join(valid_properties)}"
                )
        return properties

    return _parse_expand_properties


### PyPI VERSION CHECKER


def check_cli_update(library: Literal["huggingface_hub", "transformers"]) -> None:
    """
    Check whether a newer version of a library is available on PyPI.

    If a newer version is found, notify the user and suggest updating.
    If current version is a pre-release (e.g. `1.0.0.rc1`), or a dev version (e.g. `1.0.0.dev1`), no check is performed.

    This function is called at the entry point of the CLI. It only performs the check once every 24 hours, and any error
    during the check is caught and logged, to avoid breaking the CLI.

    Args:
        library: The library to check for updates. Currently supports "huggingface_hub" and "transformers".
    """
    try:
        _check_cli_update(library)
    except Exception:
        # We don't want the CLI to fail on version checks, no matter the reason.
        logger.debug("Error while checking for CLI update.", exc_info=True)


def _check_cli_update(library: Literal["huggingface_hub", "transformers"]) -> None:
    current_version = importlib.metadata.version(library)

    # Skip if current version is a pre-release or dev version
    if any(tag in current_version for tag in ["rc", "dev"]):
        return

    # Skip if already checked in the last 24 hours
    if os.path.exists(constants.CHECK_FOR_UPDATE_DONE_PATH):
        mtime = os.path.getmtime(constants.CHECK_FOR_UPDATE_DONE_PATH)
        if (time.time() - mtime) < 24 * 3600:
            return

    # Touch the file to mark that we did the check now
    Path(constants.CHECK_FOR_UPDATE_DONE_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(constants.CHECK_FOR_UPDATE_DONE_PATH).touch()

    # Check latest version from PyPI
    response = get_session().get(f"https://pypi.org/pypi/{library}/json", timeout=2)
    hf_raise_for_status(response)
    data = response.json()
    latest_version = data["info"]["version"]

    # If latest version is different from current, notify user
    if current_version != latest_version:
        if library == "huggingface_hub":
            update_command = _get_huggingface_hub_update_command()
        else:
            update_command = _get_transformers_update_command()

        click.echo(
            ANSI.yellow(
                f"A new version of {library} ({latest_version}) is available! "
                f"You are using version {current_version}.\n"
                f"To update, run: {ANSI.bold(update_command)}\n",
            )
        )


def _get_huggingface_hub_update_command() -> str:
    """Return the command to update huggingface_hub."""
    method = installation_method()
    if method == "brew":
        return "brew upgrade huggingface-cli"
    elif method == "hf_installer" and os.name == "nt":
        return 'powershell -NoProfile -Command "iwr -useb https://hf.co/cli/install.ps1 | iex"'
    elif method == "hf_installer":
        return "curl -LsSf https://hf.co/cli/install.sh | bash -"
    else:  # unknown => likely pip
        return "pip install -U huggingface_hub"


def _get_transformers_update_command() -> str:
    """Return the command to update transformers."""
    method = installation_method()
    if method == "hf_installer" and os.name == "nt":
        return 'powershell -NoProfile -Command "iwr -useb https://hf.co/cli/install.ps1 | iex" -WithTransformers'
    elif method == "hf_installer":
        return "curl -LsSf https://hf.co/cli/install.sh | bash -s -- --with-transformers"
    else:  # brew/unknown => likely pip
        return "pip install -U transformers"
