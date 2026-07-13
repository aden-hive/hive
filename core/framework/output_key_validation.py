"""Shared validation for declarative output key configuration."""


def _ordered_duplicates(keys: list[str]) -> list[str]:
    """Return duplicated keys ordered by their first appearance."""
    seen: set[str] = set()
    duplicate_set: set[str] = set()
    for key in keys:
        if key in seen:
            duplicate_set.add(key)
        seen.add(key)
    return list(dict.fromkeys(key for key in keys if key in duplicate_set))


def validate_output_keys(output_keys: list[str], nullable_output_keys: list[str]) -> None:
    """Raise when output key declarations are internally inconsistent."""
    errors: list[str] = []

    for field_name, keys in (
        ("output_keys", output_keys),
        ("nullable_output_keys", nullable_output_keys),
    ):
        blank_keys = [key for key in keys if not key.strip()]
        if blank_keys:
            errors.append(f"{field_name} contains empty or whitespace-only keys: {blank_keys!r}")

        duplicate_keys = _ordered_duplicates(keys)
        if duplicate_keys:
            errors.append(f"{field_name} contains duplicate keys: {duplicate_keys!r}")

    output_key_set = set(output_keys)
    orphan_nullable_keys = list(dict.fromkeys(key for key in nullable_output_keys if key not in output_key_set))
    if orphan_nullable_keys:
        errors.append(f"nullable_output_keys contains keys not present in output_keys: {orphan_nullable_keys!r}")

    if errors:
        raise ValueError("Invalid output key configuration: " + "; ".join(errors))
