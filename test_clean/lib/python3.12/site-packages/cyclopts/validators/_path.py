import pathlib
from collections.abc import Iterable, Sequence
from typing import Any

from attrs import field

from cyclopts.utils import frozen, to_tuple_converter


def ext_converter(value: None | Any | Iterable[Any]) -> tuple[str, ...]:
    return tuple(e.lower().lstrip(".") for e in to_tuple_converter(value))


@frozen(kw_only=True)
class Path:
    """Assertions on properties of :class:`pathlib.Path`.

    Example Usage:

    .. code-block:: python

        from cyclopts import App, Parameter, validators
        from pathlib import Path
        from typing import Annotated

        app = App()


        @app.default
        def main(
            # ``src`` must be a file that exists.
            src: Annotated[Path, Parameter(validator=validators.Path(exists=True, dir_okay=False))],
            # ``dst`` must be a path that does **not** exist.
            dst: Annotated[Path, Parameter(validator=validators.Path(dir_okay=False, file_okay=False))],
        ):
            "Copies src->dst."
            dst.write_bytes(src.read_bytes())


        app()

    .. code-block:: console

        $ my-script foo.bin bar.bin  # if foo.bin does not exist
        ╭─ Error ───────────────────────────────────────────────────────╮
        │ Invalid value "foo.bin" for "SRC". "foo.bin" does not exist.  │
        ╰───────────────────────────────────────────────────────────────╯

        $ my-script foo.bin bar.bin  # if bar.bin exists
        ╭─ Error ───────────────────────────────────────────────────────╮
        │ Invalid value "bar.bin" for "DST". "bar.bin" already exists.  │
        ╰───────────────────────────────────────────────────────────────╯
    """

    exists: bool = False
    """If :obj:`True`, specified path **must** exist. Defaults to :obj:`False`."""

    file_okay: bool = True
    """
    If path exists, check it's type:

    * If :obj:`True`, specified path may be an **existing** file.

    * If :obj:`False`, then **existing** files are not allowed.

    Defaults to :obj:`True`.
    """

    dir_okay: bool = True
    """
    If path exists, check it's type:

    * If :obj:`True`, specified path may be an **existing** directory.

    * If :obj:`False`, then **existing** directories are not allowed.

    Defaults to :obj:`True`.
    """

    # Can only ever really be a tuple[str, ...]
    ext: str | Sequence[str] = field(default=None, converter=ext_converter)
    """
    Supplied path must have this extension (case insensitive).
    May or may not include the ".".
    """

    def __attrs_post_init__(self):
        if self.exists and not self.file_okay and not self.dir_okay:
            raise ValueError("(exists=True, file_okay=False, dir_okay=False) is an invalid configuration.")

    def __call__(self, type_: Any, path: Any):
        if isinstance(path, Sequence):
            if isinstance(path, str):
                raise TypeError

            for p in path:
                self(type_, p)
        else:
            if not isinstance(path, pathlib.Path):
                return

            if self.ext and path.suffix.lower().lstrip(".") not in self.ext:
                if len(self.ext) == 1:
                    raise ValueError(f'"{path}" must have extension "{self.ext[0]}".')
                else:
                    pretty_ext = "{" + ", ".join(f'"{x}"' for x in self.ext) + "}"
                    raise ValueError(f'"{path}" does not match one of supported extensions {pretty_ext}.')

            if path.exists():
                if not self.file_okay and path.is_file():
                    if self.dir_okay:
                        raise ValueError(f'Only directory is allowed, but "{path}" is a file.')
                    else:
                        raise ValueError(f'"{path}" already exists.')

                if not self.dir_okay and path.is_dir():
                    if self.file_okay:
                        raise ValueError(f'Only file is allowed, but "{path}" is a directory.')
                    else:
                        raise ValueError(f'"{path}" already exists.')
            elif self.exists:
                raise ValueError(f'"{path}" does not exist.')
