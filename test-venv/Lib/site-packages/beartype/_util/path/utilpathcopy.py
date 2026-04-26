#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **path copiers** (i.e., low-level callables permanently copying
on-disk files and directories in various reasonably safe and portable ways).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar._roarexc import _BeartypeUtilPathDirException
from beartype.typing import Optional
from beartype._data.typing.datatyping import (
    CollectionStrs,
    PathnameLike,
    PathnameLikeTuple,
    TypeException,
)
from collections.abc import Callable
from pathlib import Path
from enum import (
    Enum,
    auto as next_enum_member_value,
    unique as die_unless_enum_member_values_unique,
)
from shutil import (
    copytree,
    ignore_patterns,
)

# ....................{ ENUMERATIONS                       }....................
@die_unless_enum_member_values_unique
class BeartypeDirCopyOverwritePolicy(Enum):
    '''
    Enumeration of all kinds of **directory-copying overwrite policies** (i.e.,
    competing strategies for handling edge cases in which a target path already
    exists when recursively copying directories, each with concomitant tradeoffs
    with respect to safety).

    Note that enumeration members are intentionally ordered from most safe
    (:attr:`.HALT_WITH_EXCEPTION`) to least safe (:attr:`.OVERWRITE`).

    Attributes
    ----------
    HALT_WITH_EXCEPTION : EnumMemberType
        Policy raising a fatal exception if any target path already exists. This
        constitutes the strictest and thus safest such policy.
    SKIP_WITH_WARNING : EnumMemberType
        Policy ignoring (i.e., skipping) each existing target path with a
        non-fatal warning. This policy strikes a comfortable balance between
        strictness and laxness and is thus the recommended default.
    OVERWRITE : EnumMemberType
        Policy silently overwriting each existing target path. This constitutes
        the laxest and thus riskiest such policy.
    '''

    HALT_WITH_EXCEPTION = next_enum_member_value()
    SKIP_WITH_WARNING = next_enum_member_value()
    OVERWRITE = next_enum_member_value()

# ....................{ COPIERS                            }....................
#FIXME: Unit test us up, please.
def copy_dir(
    # Mandatory parameters.
    src_dirname: PathnameLike,
    trg_dirname: PathnameLike,

    # Optional parameters.
    overwrite_policy: BeartypeDirCopyOverwritePolicy = (
        BeartypeDirCopyOverwritePolicy.HALT_WITH_EXCEPTION),
    ignore_basename_globs: Optional[CollectionStrs] = None,
    exception_cls: TypeException = _BeartypeUtilPathDirException,
    exception_prefix: str = '',
) -> None:
    '''
    Recursively copy the source directory with the passed dirname to the
    target directory with the passed dirname.

    For generality:

    * All nonexistent parents of the target directory will be recursively
      created, mimicking the action of the ``mkdir -p`` shell command on
      POSIX-compatible platforms in a platform-agnostic manner.
    * All symbolic links in the source directory will be preserved (i.e.,
      copied as is rather than their transitive targets copied instead).

    Caveats
    -------
    **This function is subject to subtle race conditions if multiple threads
    and/or processes concurrently attempt to mutate any relevant path on the
    local filesystem.** Since *all* filesystem-centric logic suffers similar
    issues, we leave this issue as an exercise for the caller.

    Parameters
    ----------
    src_dirname : PathnameLike
        Absolute or relative dirname of the source directory to be copied from.
    trg_dirname : PathnameLike
        Absolute or relative dirname of the target directory to be copied to.
    overwrite_policy : BeartypeDirCopyOverwritePolicy, default: BeartypeDirCopyOverwritePolicy.HALT_WITH_EXCEPTION
        **Directory overwrite policy** (i.e., strategy for handling existing
        paths to be overwritten by this copy). Defaults to
        :attr:`BeartypeDirCopyOverwritePolicy.HALT_WITH_EXCEPTION`, raising an
        exception if any target path already exists.
    ignore_basename_globs : Collection[str] | None, default: None
        Collection of shell-style globs (e.g., ``('*.tmp', '.keep')``) matching
        the basenames of all paths transitively owned by this source directory
        to be ignored during recursion and hence neither copied nor visited.
        Defaults to ``None``, in which case *all* paths transitively owned by
        this source directory are unconditionally copied and visited.

        Note this parameter is incompatible with the
        :attr:`BeartypeDirCopyOverwritePolicy.OVERWRITE` policy. If this
        parameter is non-:data:`None` and the ``overwrite_policy`` parameter is
        :attr:`BeartypeDirCopyOverwritePolicy.OVERWRITE`, an exception is
        raised.
    exception_cls : Type[Exception], default: _BeartypeUtilPathException
        Type of exception to be raised in the event of a fatal error. Defaults
        to :exc:`._BeartypeUtilPathException`.
    exception_prefix : str, default: ''
        Human-readable substring prefixed raised exceptions messages. Defaults
        to the empty string.

    Raises
    ------
    exception_cls
        If either:

        * The source directory does *not* exist.
        * The target directory is a subdirectory of the source directory.
          Permitting this edge case induces non-trivial issues, including
          infinite recursion from within the musty entrails of the
          :mod:`distutils` package (e.g., due to relative symbolic links).
        * The passed ``overwrite_policy`` parameter is
          :attr:`BeartypeDirCopyOverwritePolicy.HALT_WITH_EXCEPTION` *and* one or more
          subdirectories of the target directory already exist that are also
          subdirectories of the source directory. For safety, this function
          always preserves rather than overwrites existing target
          subdirectories.

    See Also
    -----------
    https://stackoverflow.com/a/22588775/2809027
        StackOverflow answer strongly inspiring this function's
        :attr:`BeartypeDirCopyOverwritePolicy.SKIP_WITH_WARNING` implementation.
    '''
    assert isinstance(src_dirname, PathnameLikeTuple), (
        f'{repr(src_dirname)} neither string nor "Path" object.')
    assert isinstance(trg_dirname, PathnameLikeTuple), (
        f'{repr(trg_dirname)} neither string nor "Path" object.')

    # ....................{ IMPORTS                        }....................
    # Avoid circular import dependencies.
    from beartype._util.path.utilpathtest import (
        die_if_dir,
        die_if_subpath,
        die_unless_dir,
    )

    # ....................{ PREAMBLE                       }....................
    # High-level "Path" objects encapsulating these dirnames.
    src_dirname = Path(src_dirname)
    trg_dirname = Path(trg_dirname)

    # If the source directory does *NOT* exist, raise an exception.
    die_unless_dir(
        dirname=src_dirname,
        exception_cls=exception_cls,
        exception_prefix=exception_prefix,
    )

    # If the target directory is a subdirectory of the source directory, raise
    # an exception. Permitting this edge case provokes issues, including
    # infinite recursion from within the musty entrails of the "distutils"
    # codebase (possibly due to relative symbolic links).
    die_if_subpath(
        parent_pathname=src_dirname,
        child_pathname=trg_dirname,
        exception_cls=exception_cls,
        exception_prefix=exception_prefix,
    )

    # If passed an iterable of shell-style globs matching ignorable basenames,
    # convert this iterable into a predicate function of the form required by
    # the shutil.copytree() function. Specifically, this function accepts the
    # absolute or relative pathname of an arbitrary directory and an iterable
    # of the basenames of all subdirectories and files directly in this
    # directory; this function returns an iterable of the basenames of all
    # subdirectories and files in this directory to be ignored. This signature
    # resembles:
    #
    #     def ignore_basename_func(
    #         parent_dirname: str,
    #         child_basenames: IterableTypes) -> IterableTypes
    ignore_basename_func: Optional[Callable] = None
    if ignore_basename_globs is not None:
        ignore_basename_func = ignore_patterns(*ignore_basename_globs)

    # ....................{ POLICIES                       }....................
    # If either:
    # * Raising a fatal exception if any target path already exists *OR*...
    # * Overwriting this target directory with this source directory...
    #
    # Then the standard shutil.copytree() function applies to this use case.
    if overwrite_policy in _COPY_DIR_OVERWRITE_POLICIES_COPYTREE:
        # Dictionary of all keyword arguments to pass to shutil.copytree(),
        # preserving symbolic links as is.
        copytree_kwargs: dict = {
            'symlinks': True,
        }

        # If raising a fatal exception if any target path already exists, do so.
        # While we could defer to the exception raised by the shutil.copytree()
        # function for this case, this exception's message erroneously refers to
        # this directory as a file and is hence best avoided as unreadable:
        #     [Errno 17] File exists: 'sample_sim'  # <-- lolbro! useless.
        if (
            overwrite_policy is
            BeartypeDirCopyOverwritePolicy.HALT_WITH_EXCEPTION
        ):
            die_if_dir(
                dirname=trg_dirname,
                exception_cls=exception_cls,
                exception_prefix=exception_prefix,
            )
        # Else, this target directory is being overwritten by this source
        # directory. In this case, silently accept this target directory if this
        # directory already exists.
        else:
            copytree_kwargs['dirs_exist_ok'] = True

        # If ignoring basenames, inform shutil.copytree() of these basenames.
        if ignore_basename_func is not None:
            copytree_kwargs['ignore'] = ignore_basename_func
        # Else, no basenames are being ignored.

        # Recursively copy this source to target directory. To avoid silently
        # overwriting all conflicting target paths, the shutil.copytree()
        # rather than dir_util.copy_tree() function is called.
        copytree(src=src_dirname, dst=trg_dirname, **copytree_kwargs)

    #FIXME: Given how awesomely flexible the manual approach implemented below
    #is, we should probably consider simply rewriting the above two approaches
    #to reuse the exact same logic. It works. It's preferable. Let's reuse it.
    #FIXME: Actually, this is increasingly critical. Third-party functions
    #called above -- notably, the dir_util.copy_tree() function -- appear to
    #suffer critical edge cases. This can be demonstrated via the BETSEE GUI by
    #attempting to save an opened simulation configuration to a subdirectory of
    #itself, which appears to provoke infinite recursion from within the musty
    #depths of the "distutils" codebase. Of course, the implementation below
    #could conceivably suffer similar issues. If this is the case, this
    #function should explicitly detect attempts to recursively copy a source
    #directory into a subdirectory of itself and raise an exception.
    #FIXME: Uncomment this if and when we actually need it. So, probably never.
    #Refactoring this out of the BETSE codebase is tedious beyond belief. *sigh*
    # # Else if logging a warning for each target path that already exists, do so
    # # by manually implementing recursive directory copying. Sadly, Python
    # # provides no means of doing so "out of the box."
    # elif overwrite_policy is BeartypeDirCopyOverwritePolicy.SKIP_WITH_WARNING:
    #     # Avoid circular import dependencies.
    #     from betse.util.path import files, paths, pathnames
    #     from betse.util.type.iterable import sequences
    #
    #     # Passed parameters renamed for disambiguity.
    #     src_root_dirname = src_dirname
    #     trg_root_dirname = trg_dirname
    #
    #     # Basename of the top-level target directory to be copied to.
    #     trg_root_basename = pathnames.get_basename(src_root_dirname)
    #
    #     # For the absolute pathname of each recursively visited source
    #     # directory, an iterable of the basenames of all subdirectories of this
    #     # directory, and an iterable of the basenames of all files of this
    #     # directory...
    #     for src_parent_dirname, subdir_basenames, file_basenames in _walk(
    #         src_root_dirname):
    #         # Relative pathname of the currently visited source directory
    #         # relative to the absolute pathname of this directory.
    #         parent_dirname_relative = pathnames.relativize(
    #             src_dirname=src_root_dirname, trg_pathname=src_parent_dirname)
    #
    #         # If ignoring basenames...
    #         if ignore_basename_func is not None:
    #             # Sets of the basenames of all ignorable subdirectories and
    #             # files of this source directory.
    #             subdir_basenames_ignored = ignore_basename_func(
    #                 src_parent_dirname, subdir_basenames)
    #             file_basenames_ignored = ignore_basename_func(
    #                 src_parent_dirname, file_basenames)
    #
    #             # If ignoring one or more subdirectories...
    #             if subdir_basenames_ignored:
    #                 # Log the basenames of these subdirectories.
    #                 logs.log_debug(
    #                     'Ignoring source "%s/%s" subdirectories: %r',
    #                     trg_root_basename,
    #                     parent_dirname_relative,
    #                     subdir_basenames_ignored)
    #
    #                 # Remove these subdirectories from the original iterable.
    #                 # Since the os.walk() function supports in-place changes to
    #                 # this iterable, this iterable is modified via this less
    #                 # efficient function rather than efficient alternatives
    #                 # (e.g., set subtraction).
    #                 sequences.remove_items(
    #                     sequence=subdir_basenames,
    #                     items=subdir_basenames_ignored)
    #
    #             # If ignoring one or more files...
    #             if file_basenames_ignored:
    #                 # Log the basenames of these files.
    #                 logs.log_debug(
    #                     'Ignoring source "%s/%s" files: %r',
    #                     trg_root_basename,
    #                     parent_dirname_relative,
    #                     file_basenames_ignored)
    #
    #                 # Remove these files from the original iterable. Unlike
    #                 # above, we could technically modify this iterable via
    #                 # set subtraction: e.g.,
    #                 #
    #                 #     subdir_basenames -= subdir_basenames_ignored
    #                 #
    #                 # For orthogonality, preserve the above approach instead.
    #                 sequences.remove_items(
    #                     sequence=file_basenames,
    #                     items=file_basenames_ignored)
    #
    #         # Absolute pathname of the corresponding target directory.
    #         trg_parent_dirname = pathnames.join(
    #             trg_root_dirname, parent_dirname_relative)
    #
    #         # Create this target directory if needed.
    #         make_unless_dir(trg_parent_dirname)
    #
    #         # For the basename of each non-ignorable file of this source
    #         # directory...
    #         for file_basename in file_basenames:
    #             # Absolute filenames of this source and target file.
    #             src_filename = pathnames.join(
    #                 src_parent_dirname, file_basename)
    #             trg_filename = pathnames.join(
    #                 trg_parent_dirname, file_basename)
    #
    #             # If this target file already exists...
    #             if paths.is_path(trg_filename):
    #                 # Relative filename of this file. The absolute filename of
    #                 # this source or target file could be logged instead, but
    #                 # this relative filename is significantly more terse.
    #                 filename_relative = pathnames.join(
    #                     trg_root_basename,
    #                     parent_dirname_relative,
    #                     file_basename)
    #
    #                 # Warn of this file being ignored.
    #                 logs.log_warning(
    #                     'Ignoring existing target file: %s', filename_relative)
    #
    #                 # Ignore this file by continuing to the next.
    #                 continue
    #
    #             # Copy this source to target file.
    #             files.copy(
    #                 src_filename=src_filename, trg_filename=trg_filename)
    # Else, this overwrite policy is unrecognized. Raise an exception.
    else:
        raise exception_cls(
            f'{exception_prefix}'
            f'overwrite policy "{overwrite_policy}" unrecognized.'
        )

# ....................{ PRIVATE ~ constants                }....................
_COPY_DIR_OVERWRITE_POLICIES_COPYTREE = frozenset((
    BeartypeDirCopyOverwritePolicy.HALT_WITH_EXCEPTION,
    BeartypeDirCopyOverwritePolicy.OVERWRITE,
))
'''
Frozen set of all **copytree-friendly directory overwrite policies** (i.e.,
:class:`.BeartypeDirCopyOverwritePolicy` enumeration members suitable for
passing as the ``overwrite_policy`` parameter to the :func:`.copy_dir` function
such that the resulting implementation reduces to a trivial call of the standard
:func:`shutil.copytree` function).
'''
