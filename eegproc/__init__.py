"""EEG preprocessing with native MNE input, outputs and ICA review."""
__version__ = "0.4.0a2"

from .configuration import PipelineConfig, resolve_config
from .api import PipelineResult, run, resume, render_report

__all__ = ["PipelineConfig", "PipelineResult", "resolve_config", "run", "resume", "render_report"]
