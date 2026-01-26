from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cyclopts.argument import ArgumentCollection


class LimitedChoice:
    def __init__(
        self,
        min: int = 0,
        max: int | None = None,
        allow_none: bool = False,
    ):
        """Group validator that limits the number of selections per group.

        Commonly used for enforcing mutually-exclusive parameters (default behavior).

        Parameters
        ----------
        min: int
            The minimum (inclusive) number of CLI parameters allowed.
            If negative, then **all** parameters in the group must have CLI values provided.
        max: int | None
            The maximum (inclusive) number of CLI parameters allowed.
            Defaults to ``1`` if ``min==0``, ``min`` otherwise.
        allow_none: bool
            If :obj:`True`, also allow 0 CLI parameters (even if ``min`` is greater than 0).
            Defaults to :obj:`False`.
        """
        self.min = min
        self.max = (self.min or 1) if max is None else max
        if self.max < self.min:
            raise ValueError("max must be >=min.")
        self.allow_none = allow_none

    def __call__(self, argument_collection: "ArgumentCollection"):
        group_size = len(argument_collection)
        populated_argument_collection = argument_collection.filter_by(value_set=True)
        n_arguments = len(populated_argument_collection)

        if self.allow_none and n_arguments == 0:
            return
        elif self.min < 0:
            # Require all arguments in the group to be supplied.
            if group_size == n_arguments:
                return
            all_names = {a.name for a in argument_collection}
            supplied_names = {a.name for a in populated_argument_collection}
            missing_names = sorted(all_names - supplied_names)
            if len(missing_names) == 1:
                raise ValueError(f"Missing argument: {missing_names[0]}")
            else:
                raise ValueError(f"Missing arguments: {missing_names}")
        elif self.min <= n_arguments <= self.max:
            return
        else:
            offenders = (
                "{"
                + ", ".join(
                    a.tokens[0].keyword if (a.tokens and a.tokens[0].keyword) else a.name
                    for a in populated_argument_collection
                )
                + "}"
            )
            if self.min == 0 and self.max == 1:
                raise ValueError(f"Mutually exclusive arguments: {offenders}")
            else:
                raise ValueError(
                    f"Received {n_arguments} arguments: {offenders}. Only [{self.min}, {self.max}] choices may be specified."
                )


class MutuallyExclusive(LimitedChoice):
    def __init__(self):
        """Alias for :class:`LimitedChoice` to make intentions more obvious.

        Only 1 argument in the group can be supplied a value.
        """
        super().__init__()


mutually_exclusive = MutuallyExclusive()
all_or_none = LimitedChoice(-1, allow_none=True)
