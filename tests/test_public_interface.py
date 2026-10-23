from dataclasses import fields
import json
from pathlib import Path
import numpy as np
import pytest
from eegproc import PipelineConfig, PipelineResult, resolve_config, run, resume
from eegproc.ica import choose_components
from eegproc.cli import parser


def test_public_names_and_config_files():
    assert PipelineConfig.__name__ == "PipelineConfig"
    assert PipelineResult.__name__ == "PipelineResult"
    assert callable(run) and callable(resume)
    names = {field.name for field in fields(PipelineConfig)}
    assert {"preset", "ica_rule", "asr_cutoff"} <= names
    assert not any("p16" in name or "balanced" in name for name in names)
    help_text = parser().format_help()
    assert "class_max" in help_text and "threshold" in help_text
    assert "--save-stages" not in help_text and "--export-audit-files" not in help_text
    for path in Path("configs").glob("*.json"):
        config = resolve_config(path)
        assert config.asr_cutoff == 20
    assert resolve_config("configs/erp.json").purpose == "erp"


@pytest.mark.parametrize("preset", ["standard", "eeglab"])
def test_ica_rule_is_independent_of_parameter_preset(preset):
    for rule in ("threshold", "class_max"):
        assert resolve_config(preset=preset,ica_rule=rule).ica_rule == rule


def test_class_max_matches_original_script_including_ties_and_boundaries():
    rng = np.random.default_rng(83)
    p = rng.dirichlet(np.ones(7), 1000)
    p = np.vstack([p, [.5,.5,0,0,0,0,0], [.5,0,.5,0,0,0,0],
                  [0,0,0,1,0,0,0], [0,0,0,0,0,0,1],
                  [.51,.49,0,0,0,0,0], [.1,.1,.3,.1,.1,.1,.2]])
    # Independent translation of find_artifacts in docs/reference/Preproc_EEGLAB_new.m.
    expected = []
    for i, probabilities in enumerate(p):
        eye = probabilities[2] == max(probabilities)
        other_artifact = any(probabilities[j] == max(probabilities) for j in (1,4,5))
        if eye or (other_artifact and probabilities[0] <= .5):
            expected.append(i)
    assert choose_components(p, resolve_config(ica_rule="class_max")) == expected
    # Threshold controls do not alter the original script's fixed class rule.
    assert choose_components(p, resolve_config(ica_rule="class_max",
        artifact_threshold=.5, brain_probability_max=0)) == expected


def test_threshold_brain_guard_and_probabilities_are_unchanged():
    p = np.array([[.05,.9,0,0,0,0,.05], [.21,.79,0,0,0,0,0],
                  [.01,.01,.01,.94,.01,.01,.01], [.1,.1,.3,.1,.1,.1,.2]])
    assert choose_components(p, resolve_config()) == [0,2]
    assert choose_components(p, resolve_config(ica_rule="class_max")) == [0,1,3]
