"""Compatibility import for eegproc; new code should import eegproc."""
from eegproc import PipelineConfig, PipelineResult, resolve_config, run, resume, render_report, __version__

__all__ = ["PipelineConfig", "PipelineResult", "resolve_config", "run", "resume", "render_report"]
