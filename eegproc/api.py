"""Code-first API; files and the command line are optional adapters."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from os import PathLike
from pathlib import Path
from typing import Any, TYPE_CHECKING
from .configuration import _config_values, resolve_config
from .settings import PipelineConfig

if TYPE_CHECKING:
    import mne
    import numpy as np
    from .epochs import EpochConfig

ConfigInput = PipelineConfig | Mapping[str, Any] | str | PathLike[str] | None


@dataclass
class PipelineResult:
    raw: mne.io.BaseRaw | None
    report: dict
    stages: dict

    @property
    def status(self):return self.report['status']

    @property
    def outputs(self):return self.report['outputs']


def run(
    raw: mne.io.BaseRaw,
    save_path: str | PathLike[str],
    subject: str,
    *,
    config: ConfigInput = None,
    config_file: str | PathLike[str] | None = None,
    montage: Any = None,
    collect_stages: bool = False,
    events: np.ndarray | Sequence[Sequence[int]] | None = None,
    event_id: Mapping[str, int] | None = None,
    epoch_config: EpochConfig | None = None,
    invocation: Mapping[str, Any] | None = None,
    **parameters: Any,
) -> PipelineResult:
    """Process a continuous MNE Raw without mutating its input.

    Scientific parameters may be supplied directly, as a mapping, or as a
    ``PipelineConfig``. An optional JSON file is the lowest-priority explicit
    base: preset defaults < file < config/base mapping < keyword parameters.
    Runtime inputs (events, output paths, montage) are separate from parameters.
    """
    from .engine import preprocess_raw

    from .parameter_resolution import adjustment, append_adjustments, audit_value
    adjustments = []
    if not isinstance(collect_stages, bool):
        adjustments.append(adjustment('collect_stages', collect_stages, False,
            'Expected a boolean; optional in-memory stage collection disabled'))
        collect_stages = False
    if config_file is not None:
        # Read an explicit file once, without expanding its defaults before
        # applying the other sources (purpose changes must remain unambiguous).
        base = _config_values(config_file)
        base.update(_config_values(config))
        effective = resolve_config(base, **parameters)
    else:
        effective = resolve_config(config, **parameters)
    if invocation is not None and not isinstance(invocation, Mapping):
        adjustments.append(adjustment('invocation', invocation, None,
            'Expected a mapping; default Python API provenance used'))
        invocation = None
    effective = append_adjustments(effective, adjustments)
    evidence = audit_value(dict(invocation or {'entrypoint': 'Python API', 'argv': None}))
    evidence.setdefault('config_precedence', 'preset < optional file < config/base < explicit parameters')
    evidence.setdefault('explicit_overrides', audit_value(parameters))
    evidence.setdefault('effective_config', asdict(effective))
    if config_file is not None:
        try:
            config_path = str(Path(config_file).resolve())
        except (TypeError, ValueError, OSError):
            config_path = audit_value(config_file)
        evidence.setdefault('config_path', config_path)
    current,report,stages=preprocess_raw(raw,save_path,subject,config=effective,
        montage=montage,collect_stages=collect_stages,events=events,event_id=event_id,
        epoch_config=epoch_config,invocation=evidence)
    return PipelineResult(None if report['status']=='awaiting_ica_review' else current,report,stages)


def resume(
    checkpoint: str | PathLike[str],
    save_path: str | PathLike[str],
    subject: str | None = None,
    *,
    selection_json: str | PathLike[str] | None = None,
    exclude: Sequence[int] | None = None,
    reviewer: str = '',
    reason: str = '',
    collect_stages: bool = False,
    original_raw: mne.io.BaseRaw | None = None,
    original_fif: str | PathLike[str] | None = None,
) -> PipelineResult:
    """Apply a complete IC exclusion list without repeating decomposition."""
    from .review import resume_ica
    raw,report,stages=resume_ica(checkpoint,save_path,subject,selection_json=selection_json,
        exclude=exclude,reviewer=reviewer,reason=reason,collect_stages=collect_stages,
        original_raw=original_raw,original_fif=original_fif)
    return PipelineResult(raw,report,stages)


def render_report(source: PipelineResult | str | PathLike[str], report_path: str | PathLike[str]) -> Path:
    """Rebuild HTML layout using saved images/diagnostics; no EEG is reprocessed."""
    from .reporting import render_report as render
    return render(source,report_path)
