# Third-party sources and notices

Version 0.4.0a1. Project-owned code and documentation are BSD-3-Clause,
as selected by the maintainer. The root LICENSE does not replace third-party
copyright notices or licenses. The root NOTICE summarizes the inventory.

| Distributed material | Source | Notice |
|---|---|---|
| `eegproc/mne_asr/` numerical routines | [EEGPrep 0.4.0](https://github.com/sccn/eegprep); original source hashes in `PROVENANCE.json` | BSD-2-Clause, SCCN; full notice in `eegproc/mne_asr/LICENSE`. Adaptations remain documented. |
| Moving-average routine in `mne_asr/_signal.py` | Syntrogi Inc. dba Intheon, 2015–2025 | Embedded MIT notice preserved; it is not replaced by the BSD notice. |
| `eegproc/resources/standard_1005.elc` | [MNE-Python 1.12.1 resource](https://github.com/mne-tools/mne-python/blob/v1.12.1/mne/channels/data/montages/standard_1005.elc) | Copied unchanged from the existing MNE distribution. [MNE BSD-3-Clause license](https://github.com/mne-tools/mne-python/blob/v1.12.1/LICENSE.txt) is reproduced in `resources/LICENSE-MNE.txt`; source, hash and usage in `resources/PROVENANCE.json`. |
| Neuracle adapter `eegproc/io/neuracle.py` | Project Python implementation using pyEDFlib; interoperability conventions described in its header | The vendor MATLAB reader is not bundled or executed. Its gain-only calibration and one-based event convention are documented behavior. The vendor's [GPL-3.0 repository](https://github.com/neuracle/neuracle-eegfile-reader) is a separate work; this project does not relicense it. |
| Report HTML, CSS and JavaScript | Project implementation | BSD-3-Clause. No fMRIPrep, niworkflows, nireports or external web framework code is bundled. |
| Three synthetic regression FIF files | Project software fixtures in `tests/fixtures/staged_v3/` | Synthetic data, not participant recordings. Historical JSON paths are sanitized in the publication snapshot; FIF contents remain unchanged. |
| Python dependencies | Their own package distributions | Installed by pip. Their notices and licenses remain applicable to those packages. No ICLabel neural-network weights or dependency source trees are copied into this repository. |

## Montage resource migration

The earlier local candidate bundled a DIPFIT resource whose redistribution
terms were not established in that audit. It is excluded from this release.
The published file is the MNE 1.12.1 resource, SHA-256
`1ee59197946d62de872db2ac7f2243a596662c231427366f6dc5d84ed237f853`.

The dictionary-to-MNE bridge reads only the native LPA, RPA and nasion and
their rigid head transform from this file. These three points and the transform
are bitwise identical to the earlier file when read with
`read_custom_montage(..., head_size=None)`. The old DIPFIT file additionally
listed O9/O10; this bridge never used the resource's channel list to assign
recording coordinates. Input channel positions still come from the supplied
MNE Raw or conversion metadata. `make_standard_montage` may use different
fiducials; it was not substituted for the existing bridge operation.

The former resource remains only in historical local evidence. No DIPFIT,
CleanLine, EEGLAB or vendor MATLAB implementation is included in this source
release. References to those workflows describe comparisons or interoperability,
not an endorsement or a claim of exact MATLAB numerical equivalence.
