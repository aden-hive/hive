from pathlib import Path
from datetime import datetime
import re


def sanitize_filename(name: str) -> str:
    return re.sub(r"[^\w\-_. ]", "_", name)


def get_export_dir() -> Path:
    """
    Export inside hive/tools/exports
    (stable location relative to package root)
    """

    current = Path(__file__).resolve()

    # Find the 'hive' folder safely
    for parent in current.parents:
        if parent.name == "hive":
            export_dir = parent / "exports"
            export_dir.mkdir(parents=True, exist_ok=True)
            return export_dir

    # fallback
    export_dir = current.parent / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    return export_dir


def build_export_path(file_name: str, extension: str, timestamp: bool = True) -> Path:
    export_dir = get_export_dir()

    file_name = sanitize_filename(file_name)

    if timestamp:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"{file_name}_{ts}"

    return export_dir / f"{file_name}.{extension}"
