# Independent MNE ASR

`mne_asr` is a local, offline Euclidean Artifact Subspace Reconstruction
implementation with native `mne.io.BaseRaw` input/output. It is not an official
MNE project and is not a new statistical ASR method. The numerical routines are
derived from EEGPrep 0.4.0's Python implementation of EEGLAB ASR; provenance,
original source hashes and licenses accompany the code.

Runtime dependencies: NumPy, SciPy, MNE. Neither EEGPrep, ASRpy nor MATLAB is
imported or required. There are no global monkey patches or EEGLAB dictionaries.
The wider preprocessing pipeline still needs its own ICA/ICLabel/PyPREP packages.

Install the containing project (the numerical ASR implementation remains
independent of EEGPrep and ASRpy):

```powershell
python -m pip install .
```

For an already high-pass-filtered continuous Raw in volts, with known bad channels
marked in `info['bads']`:

```python
from eegproc.mne_asr import clean_asr_raw

clean, qc = clean_asr_raw(raw, cutoff=20)
clean.save("asr_raw.fif", fmt="double", overwrite=True)
```

The function independently calibrates and processes each usable continuous span.
BAD, EDGE and boundary annotations split the signal. Bad and short spans are
preserved, never silently deleted or joined. Original annotations, sample grid,
absolute time, electrode positions, projections and nonselected channel samples
are retained. A channel-scoped BAD conservatively blocks the whole multichannel
span. No reconstructed data are automatically marked BAD.

Separate reference calibration is also supported:

```python
from eegproc.mne_asr import ASR

asr = ASR(cutoff=20).fit(reference_raw)
clean = asr.transform(task_raw)
reference_mask = asr.calibration_mask_
```

This uses one calibration model and resets processing state at each discontinuity.
The same channels, sampling rate, geometry, filter metadata and reference/projector
state are required; channel order may differ. Repeated transforms do not reuse
processing state from the previous recording. The caller must ensure the actual
reference scheme, hardware and preprocessing match, beyond what metadata can check.
`fit_transform(raw)` fits one model over eligible reference samples. It differs
from `clean_asr_raw`'s per-span recalibration when BAD splits are present.

## Compatibility and limitations

- Cutoff 20; reference selection window 1 s; allowed bad-channel fraction 0.075.
- Reference tolerances `(-inf, 5.5)`, matching the original script's
  `clean_rawdata -> clean_artifacts -> clean_asr` path, not the different
  standalone `clean_asr` default lower threshold.
- Calibration RMS window 0.5 s; overlap 0.66; standard Euclidean covariance.
- Processing window `max(0.5, 1.5*n_channels/sfreq)`; update step is half the window.
- Reflection at the end, MATLAB window endpoints, MATLAB default pseudoinverse
  cutoff, explicit 64 MB working budget and legacy float32 microvolt input rounding.
  Matrix calculations use float64; MNE inputs and output storage remain in volts.
- The 64 MB budget controls covariance work blocks, not total process memory.
  Raw and calibration arrays are loaded in memory. Changing the budget can change
  reconstruction update boundaries and therefore numerical output.
- Selected calibration shorter than 30 s is flagged. Spans under 20 s are skipped
  by default and reported. Those are processing policies, not evidence that every
  retained calibration or trial is suitable for scientific inference.
- Finite input is required outside blocked spans. Flat reference channels and
  numerical failures raise errors. There is no all-data calibration fallback or
  fallback to another backend. Output RMS amplification over 100x is a numerical
  catastrophe guard, not a physiological artifact threshold.
- Sampling rates must exceed 80 Hz for this spectral-shaping curve. Current local
  regression tests include 128, 250.5, 256 and 512 Hz. Dependency lower bounds are
  installation requirements, not a claim that every version combination is tested.
- The algorithm does not high-pass filter, remove line noise, rereference,
  interpolate channels, classify ICs or determine ERP trial rejection.
- No online/streaming equivalence or bitwise MATLAB identity is claimed.

`ASRConfig` exposes reference/calibration/processing settings for explicit studies.
If `config` is supplied it takes precedence over the convenience `cutoff` argument.
The default compatibility profile is the production configuration; changing
parameters creates a different profile that requires validation.

## Sources

- https://github.com/sccn/eegprep
- https://eeglab.org/plugins/clean_rawdata/
- https://www.mathworks.com/help/matlab/ref/pinv.html

See project `docs/P16_独立MNE_ASR实现与验证.md` for measured numerical agreement,
same-input simulations, public recordings, and integration checks.
