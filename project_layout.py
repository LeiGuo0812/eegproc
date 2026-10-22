"""Legacy project-path helper; installed imports no longer alter sys.path."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent


def activate_import_paths():
    """Compatibility no-op for existing local scripts."""
    return None
