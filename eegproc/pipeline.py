"""Compatibility imports; numerical stages live in dedicated modules."""
from .settings import PipelineConfig, config_for, validate_config
from .signal_ops import *
from .signal_ops import _line_clean, _training_segments, _asr_segments
from .ica import choose_components, _select_heart, _fit_ica
from .engine import preprocess_raw, _installed_versions
from importlib.metadata import version, PackageNotFoundError

def main():
    from eegproc.cli import main as cli_main
    cli_main()

if __name__ == "__main__":
    main()
