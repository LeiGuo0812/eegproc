"""Keep the public bilingual reference and runnable examples tied to the API."""
import ast
from dataclasses import fields
import importlib.util
from pathlib import Path

from eegproc import PipelineConfig
from eegproc.epochs import EpochConfig
from eegproc.mne_asr import ASRConfig

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "parameter_reference", ROOT / "scripts" / "generate_parameter_reference.py")
GENERATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GENERATOR)


def test_all_scientific_fields_have_reviewed_bilingual_descriptions():
    for cls, text in [
        (PipelineConfig, GENERATOR.DESCRIPTIONS),
        (ASRConfig, GENERATOR.ASR_DESCRIPTIONS),
        (EpochConfig, GENERATOR.EPOCH_DESCRIPTIONS),
    ]:
        descriptions = GENERATOR.entries(text)
        assert set(descriptions) == {field.name for field in fields(cls)}
        assert all(len(parts) == 3 and all(parts) for parts in descriptions.values())


def test_generated_references_match_current_defaults_api_and_cli():
    for language in ("en", "zh-CN"):
        path = ROOT / "docs" / language / "parameters.md"
        assert path.read_text(encoding="utf8") == GENERATOR.make_reference(language)


def test_public_examples_are_import_safe_and_use_public_package():
    for path in sorted((ROOT / "examples").glob("*.py")):
        source = path.read_text(encoding="utf8")
        ast.parse(source)
        assert "if __name__ ==" in source
        assert "eeg_pipeline" not in source
        spec = importlib.util.spec_from_file_location("public_example_" + path.stem, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)


def test_synthetic_example_preserves_mne_sample_convention():
    import numpy as np
    path = ROOT / "examples" / "synthetic_demo.py"
    spec = importlib.util.spec_from_file_location("synthetic_example", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    raw, events, event_id = module.make_raw()
    assert raw.get_channel_types().count("eeg") == 32
    assert event_id == {"standard": 1, "target": 2}
    assert raw.first_samp > 0
    assert events.shape == (18, 3)
    assert np.all(events[:, 0] >= raw.first_samp)
    assert any(a["description"] == "BAD_manual" and a["ch_names"] == ("F3",)
               for a in raw.annotations)
    np.testing.assert_array_equal(raw.get_data(picks=["STI"])[0, events[:, 0]-raw.first_samp], events[:, 2])
