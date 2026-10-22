# Installation

[Home](../../README.md) · [中文](../zh-CN/installation.md) · [Usage](usage.md)

## 1. Choose Python and an environment

Use **64-bit Python 3.12** for the full workflow. The standard package declares Python >=3.11; optional EEGPrep 0.4.0 requires >=3.12. Python/OS declarations describe install requirements, while observed test coverage is recorded separately in the [release audit](../RELEASE_AUDIT.md).

Windows PowerShell, using the Python launcher:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
```

The full interpreter path works without changing PowerShell execution policy. Optional activation is `.\.venv\Scripts\Activate.ps1`. After activation, use `python` in the remaining examples; otherwise replace it with `.\.venv\Scripts\python.exe`.

Linux or macOS, with Python 3.12 already installed:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
source .venv/bin/activate
```

The commands in this tutorial are for the installing user. pip downloads required dependencies into that environment. A GPU, MATLAB, EEGLAB, or a desktop Qt backend is not required to create the HTML reports. General environment guidance: [Python Packaging User Guide](https://packaging.python.org/en/latest/guides/installing-using-pip-and-virtual-environments/).

## 2. Install eegproc

Choose one of these methods.

### GitHub, without a local checkout

With Git available:

```bash
python -m pip install "eegproc @ git+https://github.com/LeiGuo0812/eegproc.git"
```

To install all optional runtime backends:

```bash
python -m pip install "eegproc[eegprep,autoreject,device] @ git+https://github.com/LeiGuo0812/eegproc.git"
```

The default branch may change. For a study, replace `REVISION` below with the release tag or full commit hash you have chosen; retain it with the analysis:

```bash
python -m pip install "eegproc @ git+https://github.com/LeiGuo0812/eegproc.git@REVISION"
```

This is a GitHub installation, not `pip install eegproc` from PyPI. See [pip VCS support](https://pip.pypa.io/en/stable/topics/vcs-support/).

### Repository ZIP or Git checkout

Download **Code → Download ZIP** from [the repository](https://github.com/LeiGuo0812/eegproc), extract it, and open a terminal in the directory containing `pyproject.toml`. Alternatively:

```bash
git clone https://github.com/LeiGuo0812/eegproc.git
cd eegproc
python -m pip install -r requirements.txt
```

Requirement files install this project as well as its dependencies. Run them from the repository root: `.` refers to the working directory. Dependency declarations are maintained once in `pyproject.toml`. [pip requirement-file syntax](https://pip.pypa.io/en/stable/reference/requirements-file-format/).

| Requirement file | Includes | Equivalent from repository root |
|---|---|---|
| `requirements.txt` | MNE, native ASR, PyPREP, Picard, ICLabel, HTML reporting | `python -m pip install .` |
| `requirements-eeglab.txt` | Standard + EEGPrep filter/channel methods for the alignment preset | `python -m pip install ".[eegprep]"` |
| `requirements-autoreject.txt` | Standard + optional local epoch interpolation | `python -m pip install ".[autoreject]"` |
| `requirements-device.txt` | Standard + Neuracle BDF preparation dependency | `python -m pip install ".[device]"` |
| `requirements-all.txt` | All optional runtime backends | `python -m pip install ".[eegprep,autoreject,device]"` |
| `requirements-dev.txt` | All runtime backends, tests, documentation/build tools | `python -m pip install ".[dev,eegprep,autoreject,device]"` |

The default ASR implementation is shipped inside eegproc; it does not require EEGPrep or ASRpy. AutoReject is needed only for `repair_epochs=True`. Ordinary MNE file readers do not require the Neuracle extra. PyTorch is a standard dependency for ICLabel; generic pip installation can be large. CPU-specific PyTorch installation, when desired, should follow [PyTorch's platform selector](https://pytorch.org/get-started/locally/) before installing eegproc.

### Wheel

If a wheel is attached to a release, download the matching version and install the actual filename:

```bash
python -m pip install eegproc-0.4.0a1-py3-none-any.whl
```

pip still resolves dependencies from the package index. Copying only a wheel to an offline computer is insufficient unless all required dependency wheels are also available.

## 3. Verify the installation

Change to a directory outside the source checkout, then run:

```bash
python -c "import eegproc; print(eegproc.__version__); print(eegproc.__file__)"
python -m eegproc --help
eegproc --help
eegproc-prepare --help
python -m pip check
```

For a regular installation, `eegproc.__file__` should be inside the active environment's `site-packages`. A source-directory import alone cannot verify installation. If the shell cannot find `eegproc`, activate the environment or use `python -m eegproc` with the environment's interpreter.

Then run the [prepared-Raw example](usage.md#resting-state-recording). A successful import checks dependency availability; the first processing run also checks electrode coordinates, usable recording duration, signal rank and metadata.

## 4. Reproducible upgrades and development

Save the installed versions alongside the study's code:

```bash
python -m pip freeze > environment.txt
```

This captures the current environment, not a universal cross-platform lock file. Keep the original prepared FIF and complete ICA checkpoint with their run report. Continuation checks numerical dependencies and computation provenance; upgrading a critical package can make a previous checkpoint incompatible.

For source development, from the checkout:

```bash
python -m pip install -e ".[dev,eegprep,autoreject,device]"
python -B -m pytest tests -q -p no:cacheprovider
python -m build --outdir dist
python -m twine check dist/*
```

Build isolation may download build dependencies. The source release excludes real recordings, historical generated results and caches; small synthetic regression fixtures remain. Study data should stay outside the repository or in ignored directories.

The optional clean-install validator creates its own isolated environment and installs dependencies when run by a user or CI:

```bash
python scripts/validate_clean_install.py --wheel dist/eegproc-0.4.0a1-py3-none-any.whl --output validation/clean-default
python scripts/validate_clean_install.py --wheel dist/eegproc-0.4.0a1-py3-none-any.whl --extras eegprep,autoreject,device --output validation/clean-all
```

Choose a new output directory. `--existing-environment-check` tests the available environment without installation and explicitly does not establish clean-install support. Refer to the [release audit](../RELEASE_AUDIT.md) and actual GitHub Actions run results for completed checks.

## Troubleshooting

| Symptom | Check |
|---|---|
| `No module named eegproc` | Use the same interpreter for pip and the script; inspect `python -m pip --version`. |
| EEGPrep refuses Python 3.11 | Create a Python 3.12 environment, or install the standard workflow without this extra. |
| pyEDFlib requires a compiler | Wheel availability depends on Python, OS and CPU. Prefer Python 3.12; inspect the [0.1.42 release files](https://pypi.org/project/pyEDFlib/0.1.42/#files). Do not infer clean support from a prepopulated environment. |
| CLI not found | Activate the environment, or run `python -m eegproc`. |
| Missing electrode locations | Correct channel names/types and set the actual acquisition montage during preparation. |
| Output already exists | Choose a new output directory or subject label. Outputs are protected from overwrite. |
| ICA continuation rejects the checkpoint | Restore the verified package/dependency versions, original input and complete checkpoint; do not edit its hashes. |
| Run completed but epochs absent | Inspect **Summary → Parameter adjustments** and **Epochs** for missing events, invalid windows, or all-rejected trials. |

eegproc uses the [BSD 3-Clause license](../../LICENSE); retained third-party terms are listed in [third-party notices](../THIRD_PARTY_NOTICES.md).
