ExtraInfoType = dict[str, str | int | float | bool | None]


class BaseKeyValueError(Exception):
    """Base exception for all KV Store Adapter errors."""

    extra_info: ExtraInfoType | None = None
    message: str | None = None

    def __init__(self, message: str | None = None, extra_info: ExtraInfoType | None = None):
        message_parts: list[str] = []

        if message:
            message_parts.append(message)

        if extra_info:
            extra_info_str = ";".join(f"{k}: {v}" for k, v in extra_info.items())
            if message:
                extra_info_str = "(" + extra_info_str + ")"

            message_parts.append(extra_info_str)

        self.message = ": ".join(message_parts)

        super().__init__(self.message)

        self.extra_info = extra_info
