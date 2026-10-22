# eegproc 0.4.0a1 release audit

Audit date: **2026-10-22**. Distribution/import name: **eegproc**. Repository: [LeiGuo0812/eegproc](https://github.com/LeiGuo0812/eegproc). This audit accompanies the GitHub alpha release; it does not claim a PyPI publication.

The release renames the package, documents its public interfaces in English and Chinese, and prepares an explicit publication snapshot. The scientific algorithms and declared parameter defaults remain unchanged. Project-owned code and documentation use the maintainer-selected [BSD 3-Clause license](../LICENSE); third-party licenses and provenance remain separately recorded in [NOTICE](../NOTICE) and [Third-party sources and notices](THIRD_PARTY_NOTICES.md).

## Verification record

Local scientific checks use an existing Windows Python **3.13.14** environment. No additional dependency packages were downloaded or installed on the maintainer's machine during this release preparation. That evidence is distinct from installation checks performed by GitHub Actions in fresh hosted environments.

| Check | Result or evidence | Scope |
|---|---|---|
| Package and public names | Distribution/import `eegproc`; CLI `eegproc` and `eegproc-prepare`; `python -m eegproc` | Previous `eeg_pipeline` imports and old CLI names are retained as compatibility aliases. |
| Dependency declarations | `pyproject.toml` is the single source; six requirements files select standard/runtime/development extras | Dependencies are downloaded by the installing user or CI. Requirements are not universal lock files. |
| Exact pinned PyPI releases | All seven pinned releases exist with non-yanked distributions in the metadata inspected on the audit date | Availability details and Python constraints are retained below. Metadata verification did not download package archives. |
| Local regression suite | Completed full run: **387 passed, 1 skipped**; subsequent targeted release checks: **27 passed, 1 skipped**, including the new Git-checkout preservation test | Existing environment. The skipped test requires Windows symbolic-link creation permission. |
| Five-case numerical regression | Continuous data are **bitwise equal** for rest, ERP, class-maximum IC selection, EEGLAB-parameter alignment and the long-recording case | MNE Info/annotations, ICA decomposition and probabilities, ASR diagnostics and epochs also agree with the validated pre-rename results. |
| Historical ICA continuation | **12** previous checkpoints accepted by production compatibility rules and continued; maximum signal difference **1.50348e-20 V** | No temporary compatibility bypass. Source/target transitions, input identity and critical dependency checks remain active. |
| Complete synthetic example | Rest, ERP, ICA review, continuation and report rebuilding completed; **17/18** ERP trials retained | Standard 8/9, target 9/9; the generated input contains a deliberate manual BAD annotation. This checks software behavior, not clinical performance. |
| Synthetic continuation | Same selection reproduced the ERP result within **7.5047e-19 V** | No refitting; no report plotting errors observed. |
| Batch and downstream examples | Batch example and PSD/ERP/time-frequency analysis scripts completed | Examples are executable with current APIs; generated analysis files are separate from the compact preprocessing outputs. |
| Documentation | English/Chinese installation, parameter reference, complete usage, report interpretation and further analysis; local links checked | **42** Python code blocks parsed successfully. PSD integration, ERP contrast and padded-epoch Morlet APIs were also exercised with MNE 1.12.1. |
| Montage resource | Replaced the earlier local DIPFIT resource with the unchanged MNE 1.12.1 resource and its BSD notice | The bridge uses only LPA/RPA/nasion and their native head transform; those values are bitwise unchanged. Recording channel coordinates still come from input metadata. |
| Public source boundary | `scripts/stage_release.py` builds `release/eegproc/` from an explicit allowlist | Includes code, documentation, examples, tests, licenses and a relative-path/hash manifest; excludes real recordings, historical result trees and caches. |
| Repeated staging | Previous snapshots are preserved under `_待手动删除_release_<timestamp>/` within the research project | Resolved destination/archive paths are checked; research data are not removed or moved outside the project. |
| Offline build inspection | `scripts/offline_build.py` builds sdist and wheel using already installed build tools and inspects their contents | Final artifact hashes and sizes belong to the build evidence and release assets; an offline build does not verify fresh dependency resolution. |
| Hosted clean installation | The [first publication run](https://github.com/LeiGuo0812/eegproc/actions/runs/39808816831) passed all six Ubuntu/Windows jobs on Python 3.11, 3.12 and 3.13 | Both Python 3.12 jobs passed **388 tests, 1 skipped**, with all runtime extras. Other jobs ran the documented base subset. Check the linked workflow for the exact release commit and later documentation updates. |

Small nonzero continuation differences reflect save/load and numerical reconstruction tolerances in the verified environment. The five-case bitwise comparison and checkpoint continuation checks address separate contracts; neither proves identical output under every future dependency version or biological superiority over another preprocessing method.

## Publication contents

```text
eegproc/
├── pyproject.toml / MANIFEST.in / requirements*.txt
├── README.md / README.zh-CN.md / LICENSE / NOTICE / .gitignore
├── eegproc/                     Runtime package, ASR and licensed montage
├── eeg_pipeline/                Previous import-name compatibility aliases
├── mne_asr/                     Compatibility import
├── *.py                         Preparation and compatibility entry points
├── configs/ / examples/         Optional presets and complete executable examples
├── docs/
│   ├── en/ / zh-CN/             Installation, parameters, use, results and analysis
│   └── assets/                  Figures generated from synthetic tutorial data
├── tests/                       Unit tests and fixed synthetic regression data
├── scripts/                     Staging, build and validation helpers
├── .github/workflows/           Hosted installation/regression checks
└── RELEASE_MANIFEST.json        Relative paths, hashes and sanitization records
```

Staging does not recursively copy the research workspace. The allowlist is the publication boundary, with `.gitignore` as an additional guard. The manifest records source and staged SHA-256 values, including transformations applied to historical fixture metadata.

Three small synthetic regression FIFs are included, approximately **3.45 MB** in total. Their reviewed subject, experimenter, project and description fields were absent; FIF bytes are retained for regression fidelity. Historical fixture JSON copies have personal absolute-path prefixes removed in staging while numerical values and reference hashes remain intact. The original workspace evidence is preserved. Tutorial figures contain generated signals, not participant recordings.

## Installation checks and supported scope

Use [English installation](en/installation.md) or [中文安装教程](zh-CN/installation.md). Python **3.12** is the recommended complete-feature environment. The standard package declares Python >=3.11; optional EEGPrep requires >=3.12.

The hosted workflow builds distributions, creates an isolated environment, installs the built wheel and requested dependencies, runs `pip check`, exercises the actual console entry points outside the checkout, and checks synthetic rest/ERP, metadata, manual BAD preservation, ICA continuation and HTML delivery. It then runs the applicable regression tests. The worker blocks network connections during signal processing; dependency installation itself uses the network.

| Hosted matrix | Requested scope |
|---|---|
| Ubuntu / Windows, Python 3.11 | Standard workflow, AutoReject/device extras and selected base regression tests |
| Ubuntu / Windows, Python 3.12 | All runtime extras and full regression suite |
| Ubuntu / Windows, Python 3.13 | Experimental standard workflow; device/EEGPrep extras excluded |

The matrix describes requested checks, not a blanket support claim. Read the [run status and artifacts](https://github.com/LeiGuo0812/eegproc/actions/workflows/tests.yml) for the exact version. Python 3.13 jobs are experimental; macOS and CUDA execution are not covered by that matrix. CI explicitly uses official CPU PyTorch wheels.

`--existing-environment-check` in the validator exercises available dependencies without installing them and records `clean_install_verified=false`. It must not be presented as a clean-install result. Compatibility decisions for existing ICA checkpoints still depend on the verified computational source, dependency versions and original recording identity.

## Known boundaries

- **Annotation-to-STIM fallback:** when annotations contain only BAD labels but events are in STIM, `event_source="auto"` can fail before STIM fallback. Use `event_source="stim"` or explicit `events`/`event_id`. Inspect the Epochs section and parameter audit: continuous processing can finish while optional epoch export is skipped.
- **Scientific defaults:** the existing settings are retained, not newly optimized by the package rename. `preset="eeglab"` is Python parameter alignment within the same workflow, not exact MATLAB numerical reproduction.
- **IC selection:** the default Heart-only ICLabel candidate additionally requires ECG correlation when usable ECG exists; without usable ECG it uses ICLabel alone. The current ECG gate is not a separate OR-based artifact detector.
- **QC decisions:** the default report policy completes viable processing and records observations. A completed status is not automatic scientific acceptance. Quality review, event definitions and study-specific inclusion criteria remain necessary.
- **Tutorial analyses:** PSD, ERP and time-frequency figures illustrate actual software outputs. The compact short-epoch time-frequency example is explicitly exploratory; use appropriate padding and baseline for scientific inference.
- **Installation breadth:** dependency availability and existing-environment regression do not prove every OS/Python combination. Preserve actual run provenance and assess scientific changes before upgrading a study environment.

## Licenses and provenance

The maintainer selected BSD-3-Clause for project-owned material. The independent ASR implementation retains EEGPrep/SCCN BSD-2-Clause provenance and the embedded Intheon MIT notice. The bundled montage is now the MNE 1.12.1 distribution resource, with its exact source/hash and MNE license included. The earlier DIPFIT file is excluded from this release; the bridge geometry used by processing is unchanged.

The Neuracle adapter is the project's Python implementation using pyEDFlib and documented interoperability conventions. The vendor MATLAB reader is not bundled or executed, and its separate GPL license is not replaced by this project's license. Report HTML/CSS/JavaScript are project code; fMRIPrep, niworkflows and nireports implementations are not bundled. See the complete [third-party inventory](THIRD_PARTY_NOTICES.md).

## Public dependency availability

The following exact releases were checked against the official PyPI release
pages and JSON API on 2026-10-22. Only metadata was fetched. A listed wheel is
evidence of a published artifact, not proof of a successful dependency solve or
runtime test on every platform.

| Pinned release | Earliest upload (UTC) | Requires-Python | Non-yanked artifacts |
|---|---|---|---|
| [mne 1.12.1](https://pypi.org/project/mne/1.12.1/) | 2026-04-20 | `>=3.10` | Universal Python wheel and sdist |
| [mne-icalabel 0.10.0](https://pypi.org/project/mne-icalabel/0.10.0/) | 2026-10-05 | `>=3.10` | Universal Python wheel and sdist |
| [pyprep 0.5.0](https://pypi.org/project/pyprep/0.5.0/) | 2025-07-17 | `>=3.9` | Universal Python wheel and sdist |
| [python-picard 0.8.2](https://pypi.org/project/python-picard/0.8.2/) | 2026-04-27 | `>=3.7` | Universal Python wheel and sdist |
| [eegprep 0.4.0](https://pypi.org/project/eegprep/0.4.0/) | 2026-09-23 | `>=3.12` | Universal Python wheel and sdist |
| [autoreject 0.4.3](https://pypi.org/project/autoreject/0.4.3/) | 2023-11-14 | `~=3.8` | Universal Python wheel and sdist |
| [pyedflib 0.1.42](https://pypi.org/project/pyEDFlib/0.1.42/) | 2025-06-26 | Not specified in release metadata | Platform-specific wheels and sdist |

Python **3.12** is the practical installation target for all optional backends.
The base package's Python 3.11 lower bound does not make the EEGPrep extra
installable on Python 3.11. The extra is not silently skipped to hide that
restriction.

pyEDFlib 0.1.42 publishes Windows x64 and Linux x64 wheels for CPython 3.11 and
3.12. Its only CPython 3.13 wheel in the inspected release is Linux aarch64;
Windows x64 and Linux x64 Python 3.13 installation can require a source build.
The existing local Python 3.13 installation therefore does not establish
compiler-free fresh installation of the device extra.

The pinned MNE release additionally requires SciPy `>=1.13` and NumPy
`>=1.26,<3`; EEGPrep adds NumPy `>=2.1.0` and SciPy `>=1.14.1` outside macOS
(`>=1.16.3` on macOS). pip combines those upstream requirements with this
project's direct requirements. These bounds have not been tested exhaustively.
