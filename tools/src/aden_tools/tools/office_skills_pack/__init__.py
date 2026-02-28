from .contracts import ArtifactError, ArtifactResult, CONTRACT_VERSION


def register_office_skills_pack(mcp) -> None:
    from .register import register_office_skills_pack as _register_office_skills_pack

    _register_office_skills_pack(mcp)

__all__ = [
    "ArtifactError",
    "ArtifactResult",
    "CONTRACT_VERSION",
    "register_office_skills_pack",
]
