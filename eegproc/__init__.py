"""EEG preprocessing with native MNE input, outputs and ICA review."""
__version__ = "0.4.0a5"

from .configuration import PipelineConfig, resolve_config
from .api import PipelineResult, run, epoch, resume, render_report

__all__ = ["PipelineConfig", "PipelineResult", "resolve_config", "run", "epoch", "resume", "render_report"]
