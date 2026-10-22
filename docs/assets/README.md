# Tutorial figures

These three PNG files were generated locally from `examples/synthetic_demo.py` and `examples/analyze_outputs.py` using eegproc 0.4.0a1 and MNE 1.12.1. They contain generated signals, not participant recordings.

Reproduce from the repository root after installation:

```bash
python examples/synthetic_demo.py --output outputs/demo
python examples/analyze_outputs.py --raw outputs/demo/rest/synthetic_cont_raw.fif --output analysis/demo_rest
python examples/analyze_outputs.py --epochs outputs/demo/erp/synthetic_clean-epo.fif --output analysis/demo_erp
```

| Documentation file | Script output |
|---|---|
| `synthetic_rest_psd.png` | `analysis/demo_rest/rest_psd.png` |
| `synthetic_condition_erp.png` | `analysis/demo_erp/condition_erp.png` |
| `synthetic_time_frequency.png` | `analysis/demo_erp/time_frequency.png` |

The observed example retained 17/18 ERP trials, including a deliberately inserted manual BAD annotation: standard 8/9, target 9/9. Exact numeric outputs can depend on the scientific dependency versions. The short-epoch time-frequency figure is a rendering demonstration; use longer padded epochs for inferential time-frequency analysis. These figures do not establish comparative denoising accuracy.
