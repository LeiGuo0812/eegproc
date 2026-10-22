"""Generate bilingual references from live defaults and reviewed descriptions."""
from __future__ import annotations

import argparse
from dataclasses import fields
import inspect
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
B = chr(96)

# Name | constraint/unit | English | Chinese
DESCRIPTIONS = """
preset|standard / eeglab|Default parameter set within the same pipeline. eeglab approximates the original script; it does not reproduce MATLAB numerically.|同一流程的参数默认值；eeglab 近似对齐原脚本，不代表 MATLAB 数值复现。
purpose|rest / erp|Analysis defaults; does not itself enable epoch export.|分析目的默认值，不单独开启分段。
task_name|str / None; 1–100 characters|Task metadata, independent of purpose, filenames and event selection. No surrounding whitespace/control characters.|任务名称元数据，独立于 purpose、文件名和事件筛选；无首尾空格或控制字符。
filter_method|mne_fir / eeglab_fir / off|Analysis/training FIR implementation; off skips explicit band filtering.|分析与训练数据的 FIR 实现；off 跳过显式带通滤波。
filter_order|even int ≥ 2; samples|Used by eeglab_fir only; MNE FIR chooses its own length.|仅 eeglab_fir 使用；MNE FIR 自行确定滤波长度。
filter_position|after_reference|Currently the only supported filter position.|目前仅支持在参考处理之后滤波。
highpass|Hz > 0; < lowpass|Analysis high-pass edge; limited by existing acquisition filtering.|分析高通边缘，受已有采集滤波限制。
lowpass|Hz > highpass; < Nyquist|Analysis low-pass edge; may be clipped to input limits.|分析低通边缘，必要时根据输入限制下调。
training_highpass|Hz > 0; < training_lowpass|ICA training high-pass edge. Identical analysis/training bands reuse the filtered signal.|ICA 训练高通边缘；分析与训练频段相同时复用滤波信号。
training_lowpass|Hz > training_highpass; < Nyquist|ICA training low-pass edge; nominal ICLabel training is 1–100 Hz.|ICA 训练低通边缘；ICLabel 标准训练频段为 1–100 Hz。
line_method|spectrum_fit / notch / off|Line-noise method; spectrum_fit uses MNE multitaper sinusoidal fitting.|工频方法；spectrum_fit 使用 MNE 多锥窗正弦拟合。
line_frequency|Hz > 0 / None|Known mains frequency, normally 50 or 60; harmonics up to min(100, sfreq/2−1) Hz. None disables removal. Not an automatic estimator.|已知工频，通常为 50 或 60；处理不超过 min(100, sfreq/2−1) Hz 的谐波；None 关闭，不自动估计。
line_window_seconds|seconds > 0|spectrum_fit window. Unsupported DPSS settings reset to 4 s / 2 Hz; unusably short spans are reported.|spectrum_fit 窗长；不支持的 DPSS 组合恢复 4 秒 / 2 Hz；过短片段记录在报告。
line_bandwidth|Hz > 0|Multitaper bandwidth; inactive for notch/off.|多锥窗带宽；notch/off 时不使用。
line_p_value|0 < p < 1|spectrum_fit significance threshold; inactive for notch/off.|spectrum_fit 显著性阈值；notch/off 时不使用。
channel_method|pyprep / eegprep / off|Bad-channel detector; eegprep needs an optional extra. Input bad channels remain relevant when off.|坏导检测器；eegprep 需可选依赖；off 仍保留输入坏导信息。
flatline_seconds|seconds > 0|Flatline duration for the EEGPrep-compatible detector.|EEGPrep 兼容检测器的平直时长阈值。
channel_correlation|0 < fraction < 1|EEGPrep-compatible correlation threshold; does not replace PyPREP internal settings.|EEGPrep 兼容相关阈值，不替代 PyPREP 内部参数。
channel_broken_fraction|0 < fraction < 1|EEGPrep-compatible fraction of failed channel windows.|EEGPrep 兼容检测中异常窗口比例。
detect_ransac|bool|PyPREP RANSAC switch; needs suitable electrode geometry/channel count.|PyPREP RANSAC 开关；需要合适的坐标与导联数量。
reference|average / unchanged|Reference method for initial and enabled final reference; unchanged skips both.|初始及启用后的最终参考方法；unchanged 均不改变参考。
interpolate_bads|bool|Global interpolation gate; False also disables pre-ASR interpolation.|总插值开关；False 同时关闭 ASR 前插值。
interpolate_before_asr|bool|Interpolate before ASR only if interpolate_bads=True; changes the spatial ASR input.|仅 interpolate_bads=True 时在 ASR 前插值；改变 ASR 空间输入。
final_interpolation|bool|Final interpolation, also gated by interpolate_bads.|最终插值，同时受 interpolate_bads 控制。
final_reference|bool|Apply the chosen reference after artifact handling; reference=unchanged still skips rereferencing.|伪迹处理后应用所选参考；reference=unchanged 时仍不重参考。
exclude_gross_from_training|bool|Exclude gross artifacts from ICA training without deleting delivered continuous samples.|将严重伪迹排除出 ICA 训练，不删除最终连续数据样本。
residual_qc|bool|Generate continuous BAD_residual annotations and residual diagnostics.|生成连续 BAD_residual 标注与残留诊断。
ica_enabled|bool|Enable ICA/ICLabel/application. False deactivates review/manual selection.|启用 ICA、ICLabel 与成分处理；False 时复核/人工选择失效。
ica_mode|auto / review / manual|auto applies a proposal; review pauses before subtraction; manual applies a complete explicit list.|auto 应用建议；review 在减除前暂停；manual 应用完整人工列表。
ica_exclude|tuple[int] / None; zero-based|Complete list; [] keeps all. Supplying a list in auto selects manual. Invalid/out-of-range indices are audited, never replaced with automatic choices.|完整删除列表，0 起始；[] 全保留；auto 下传列表会转 manual；无效或越界编号记录，不用自动建议替代。
ica_rule|threshold / class_max|Automatic selection rule defined below; does not change ICA fitting.|自动筛选规则见下文；不改变 ICA 拟合。
artifact_threshold|0.5 ≤ probability ≤ 1|threshold only: minimum maximum Muscle/Eye/Heart/Line/Channel probability.|仅 threshold：肌电/眼电/心电/工频/通道噪声中最高概率的最低要求。
brain_probability_max|0 ≤ probability ≤ 0.5|threshold only: largest Brain probability allowed for removal.|仅 threshold：删除时允许的 Brain 概率上限。
heart_min_ecg_correlation|0 ≤ absolute r ≤ 1|threshold only: extra AND gate for Heart-only candidates with a usable real ECG. Without ECG, use ICLabel alone.|仅 threshold：有真实可用 ECG 时对纯 Heart 候选增加 AND 相关门控；无 ECG 时仅用 ICLabel。
ica_backend|mne|Supported ICA interface; solver is selected by ica_method.|支持的 ICA 接口；求解器由 ica_method 指定。
ica_method|picard / infomax|Extended-Infomax objective with Picard or MNE Infomax solver.|使用 Picard 或 MNE Infomax 求解扩展 Infomax 目标。
ica_max_iter|int ≥ 1|Iteration limit; limit/convergence diagnostics are reported.|最大迭代数；报告记录收敛和达到上限情况。
ica_tolerance|positive|Picard tol or Infomax w_change; identical values need not mean identical stopping behavior.|Picard tol 或 Infomax w_change；相同数值不代表相同停止行为。
rank_method|relative / covariance|relative: singular values > max(machine-precision tolerance, largest singular value × 1e-6). covariance: min(matrix_rank, covariance eigenvalues > 1e-7 µV²).|relative：奇异值大于 max(机器精度容差, 最大奇异值×1e-6)；covariance：矩阵秩与大于 1e-7 µV² 的协方差特征值数的较小值。
review_author|str|Reviewer label for an initial manual decision.|初次人工决策复核人标签。
review_reason|str|Reason for an initial manual decision.|初次人工决策理由。
asr_cutoff|positive / None|Burst cutoff; None disables ASR. Default 20 for both rest and ERP.|爆发阈值；None 关闭；rest 和 ERP 默认均为 20。
asr_backend|mne_native|Independent MNE-compatible ASR; no runtime ASRpy dependency.|独立兼容 MNE 的 ASR；运行时不依赖 ASRpy。
asr_options|dict / None|Advanced overrides below; cutoff/min_segment_seconds use top-level settings.|高级覆盖见下表；cutoff/min_segment_seconds 使用顶层参数。
seed|int; 0 ≤ seed < 2**32|Random seed for ICA and applicable detection/repair stages.|ICA 与适用的检测/修复阶段的随机种子。
n_threads|int ≥ 1|Numerical thread limit, not recording-level batch scheduling.|数值线程数，不自动调度记录级批处理。
bad_channel_fraction_limit|0 < fraction < 1|Global bad-channel quality threshold; policy determines reporting/stopping.|全局坏导比例质控阈值，由 policy 决定报告或停止。
bad_channel_policy|auto / report / stop|report continues viable processing; stop rejects excess bad channels; auto resolves to report with the supported mne_native backend. At least 8 usable EEG channels remain required.|report 在仍可计算时跑完；stop 在坏导超限时停止；auto 对当前 mne_native 后端等于 report；始终要求至少 8 个可用 EEG 导联。
min_training_seconds|seconds > 0|Minimum usable training and ASR segment duration; not proof of adequate calibration.|最短训练与 ASR 片段时长，不代表校准质量已充分。
gross_peak_uv|µV > 0|Absolute peak threshold for gross training artifacts.|严重训练伪迹绝对峰值阈值。
residual_peak_uv|µV > 0|Residual absolute peak threshold, also the default epoch screen.|残留绝对峰值阈值，也是默认分段阈值。
residual_ptp_uv|µV > 0|Residual peak-to-peak threshold, also the default epoch screen.|残留峰峰值阈值，也是默认分段阈值。
residual_robust_z|positive robust z|Relative log-SD threshold, gated by residual_relative_min_ptp_uv.|对数标准差的相对稳健 z 阈值，同时受最小峰峰值限制。
residual_relative_min_ptp_uv|µV > 0|Minimum peak-to-peak for a relative-noise rejection.|触发相对噪声标准所需最小峰峰值。
window_seconds|seconds > 0|Continuous gross/residual screening window.|连续严重/残留伪迹筛查窗口。
guard_seconds|seconds ≥ 0|Padding around detected continuous artifact windows.|连续伪迹窗口周围扩展时间。
epoch_mode|none / events / fixed|Epoch export. Passing explicit events to run activates events if mode is none.|可选分段；run 显式传 events 时 none 自动改为 events。
epoch_qc|auto / event-window / annotations|auto uses event-window for event epochs (either purpose) and annotations for fixed windows. Original BAD always preserved.|auto 对两种 purpose 的事件分段均用 event-window，对固定窗用 annotations；始终保留原有 BAD。
repair_epochs|bool|Opt-in AutoReject repair, ERP events with event-window QC only; requires extra. Continuous samples unchanged.|可选 AutoReject 局部修复，仅适用于 ERP 事件窗 QC；需依赖；不改连续样本。
epoch_tmin|seconds ≤ 0|Event epoch start relative to onset.|相对事件起点的分段开始时间。
epoch_tmax|seconds > 0|Event epoch end; sample rounding follows MNE.|相对事件起点的结束时间，端点取整遵循 MNE。
epoch_baseline|(start, end) / None; seconds|Within event window; None endpoints mean boundaries; whole None disables baseline. Fixed epochs have no baseline.|位于事件窗内；端点 None 表示边界，整体 None 关闭；固定窗无基线校正。
fixed_epoch_duration|seconds > 0|Fixed window duration; last sample at duration − 1/sfreq.|固定窗时长，最后样本时间为 duration − 1/sfreq。
fixed_epoch_overlap|seconds; 0 ≤ overlap < duration|Fixed-window overlap; starts must differ by at least one sample.|固定窗重叠，相邻起点至少差一个样本。
event_source|auto / annotations / stim|Without explicit events. For STIM-only recordings explicitly use stim or pass events.|无显式 events 时使用；仅 STIM 的数据请明确设 stim 或传 events。
event_names|tuple[str] / None|Select names from event_id; None retains mapping. Unknown names skip epochs with an audit.|按 event_id 名称筛选；None 保留映射；未知名称跳过分段并记录。
stim_channel|str / None|Actual STIM channel name; ignored for explicit events or annotation extraction.|真实 STIM 通道名；显式事件或标注提取时不用。
report_full_record_heatmap|bool|Optional full-record heatmap; off keeps reports compact.|可选全程热图；默认关闭以缩小报告。
report_waveform_windows|int ≥ 1|Number of representative before/after waveform windows.|代表性处理前后波形窗口数量。
report_window_seconds|seconds > 0|Duration of each representative waveform window.|每个代表性波形窗口时长。
report_max_channels|int ≥ 2|Maximum displayed channels in representative waveforms.|代表性波形最多显示通道数。
report_dpi|int ≥ 60; dpi|Raster resolution; larger values increase HTML size.|图片分辨率，越大则 HTML 越大。
report_max_width|int ≥ 600; pixels|Maximum stored report figure width.|报告内图片最大像素宽度。
report_psd_windows|int ≥ 1|Maximum representative windows for report PSD.|报告 PSD 抽取的代表性窗口数量上限。
report_psd_window_seconds|seconds > 0 / None|None uses bounded automatic sampling. Report PSD is diagnostic, not a final analysis estimate.|None 使用内部有界抽样；报告 PSD 用于诊断，不是正式分析估计。
"""

ASR_DESCRIPTIONS = """
cutoff|positive; use asr_cutoff|Burst cutoff, controlled at pipeline level.|爆发阈值，由顶层控制。
reference_window|seconds > 0|Reference-selection window.|参考段筛选窗口。
reference_max_bad_channels|0 ≤ fraction < 1|Maximum bad-channel fraction in reference windows.|参考窗口坏导比例上限。
reference_tolerances|(lo, hi); lo < 0 < hi; lo can be -inf|Robust reference acceptance interval; supply -inf through Python rather than nonstandard JSON.|稳健参考段接收区间；-inf 用 Python 设置，避免非标准 JSON。
calibration_window|seconds > 0|Calibration window.|校准窗口。
overlap|0 ≤ fraction < 1|Reference/calibration window overlap.|参考与校准窗重叠比例。
processing_window|seconds > 0 / None|Effective window=max(requested or 0.5, 1.5 × usable EEG channels / sfreq).|实际窗口=max(指定值或0.5, 1.5×可用EEG导联数/sfreq)。
step_size|int ≥ 1 / None; samples|None uses floor(sfreq × effective processing window / 2); explicit step may not exceed the window samples.|None 使用 floor(sfreq×实际处理窗/2)；指定值不能超过处理窗样本数。
max_dimensions|0 < fraction < 1|Maximum reconstructed subspace fraction.|最大重建子空间比例。
max_memory_mb|MB > 0|ASR block budget also affects update boundaries and numerical results.|分块内存预算也影响更新边界与数值结果。
min_segment_seconds|seconds > 0; use min_training_seconds|Minimum eligible segment, controlled at pipeline level.|可处理片段最短时长，由顶层控制。
amplification_limit|positive ratio|Maximum output/input RMS ratio; a violation stops ASR with a numerical-instability error.|输出/输入 RMS 比值上限；超限以数值不稳定错误停止 ASR。
"""

EPOCH_DESCRIPTIONS = """
tmin|seconds ≤ 0|Inherited from resolved epoch_tmin unless explicitly supplied.|默认继承解析后的 epoch_tmin。
tmax|seconds > 0|Inherited from resolved epoch_tmax.|默认继承解析后的 epoch_tmax。
baseline|tuple / None; seconds|Inherited from epoch_baseline.|默认继承 epoch_baseline。
peak_uv|µV > 0|Inherited from residual_peak_uv.|默认继承 residual_peak_uv。
ptp_uv|µV > 0|Inherited from residual_ptp_uv.|默认继承 residual_ptp_uv。
robust_z|positive|Inherited from residual_robust_z.|默认继承 residual_robust_z。
relative_min_ptp_uv|µV > 0|Inherited from residual_relative_min_ptp_uv.|默认继承 residual_relative_min_ptp_uv。
max_interpolate|int ≥ 1; channels|Local repair cap, also limited by floor(n_EEG × max_local_fraction).|局部插值上限，同时不超过 floor(n_EEG × max_local_fraction)。
max_local_fraction|0 < fraction ≤ 0.25|Maximum local interpolation fraction.|局部插值比例上限。
min_fit_epochs|int ≥ cv|Minimum eligible epochs to fit AutoReject.|拟合 AutoReject 的最少可用试次数。
cv|int ≥ 2|AutoReject cross-validation folds.|AutoReject 交叉验证折数。
seed|int; 0 ≤ seed < 2**32|Inherited from pipeline seed.|默认继承流程 seed。
"""


def entries(text):
    return {row.split("|", 1)[0]: row.split("|")[1:] for row in text.strip().splitlines()}


def table(cls, descriptions, language, configs=None):
    desc = entries(descriptions)
    definitions = fields(cls)
    if set(desc) != {field.name for field in definitions}:
        raise ValueError(f"Incomplete {cls.__name__}: {set(desc) ^ {f.name for f in definitions}}")
    zh = language == "zh-CN"
    columns = ["参数", "类型", "有效值 / 单位", "说明"] if zh else ["Parameter", "Type", "Values / units", "Meaning"]
    columns += ["standard/rest", "standard/erp", "eeglab/rest", "eeglab/erp"] if configs else ["类默认值" if zh else "Class default"]
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    for field in definitions:
        domain, en, cn = desc[field.name]
        annotation = str(field.type).replace("<class '", "").replace("'>", "").replace("|", "/")
        values = [f"{B}{field.name}{B}", annotation, domain, cn if zh else en]
        defaults = [getattr(c, field.name) for c in configs] if configs else [field.default]
        values += [f"{B}{default!r}{B}" for default in defaults]
        lines.append("| " + " | ".join(v.replace("\n", " ") for v in values) + " |")
    return "\n".join(lines)


INTRO = {
"en": """# Parameter reference

[简体中文](../zh-CN/parameters.md) · [Installation](installation.md) · [Usage](usage.md)

All {count} PipelineConfig fields are listed below. Defaults are generated from the current code for four purpose/preset combinations. Both presets follow the same pipeline.

## Configuration in Python

Priority: **preset defaults < optional JSON file < config object/mapping < explicit run keywords**. A PipelineConfig is immutable and fully resolved: all its fields become explicit when passed as a base. Construct a new config to obtain a new purpose's defaults rather than changing only purpose on an existing config.
""",
"zh-CN": """# 参数参考

[English](../en/parameters.md) · [安装](installation.md) · [使用](usage.md)

本页包含全部 {count} 个 PipelineConfig 字段，四组默认值由当前代码生成。两种预设遵循同一流程。

## Python 配置方法

优先级：**预设默认值 < 可选 JSON 文件 < config 对象/字典 < run 显式关键字参数**。PipelineConfig 是完整解析后的不可变对象，作为配置源时全部字段均视为显式值。切换目的并重新获取默认值时，应新建配置，而不是只改已有配置的 purpose。
"""}

POLICY = {
"en": """
## Corrections, dependencies and failure boundaries

- Unknown fields are ignored; unsupported types, values and choices generally revert to the selected purpose/preset defaults. Every correction enters config.adjustments and the HTML parameter audit. An unreadable optional config file does not prevent using code parameters.
- Bands are constrained by acquisition filtering and Nyquist. Removed frequencies are not restored; no implicit resampling occurs. At sfreq ≤80 Hz the current ASR backend is disabled; below 100 Hz the current ICA/ICLabel stage is disabled, with an audit.
- Disabled ICA cancels review/manual selection. Review pauses without applying a final list. Malformed manual lists keep all components and require review; unavailable indices are omitted, including during resume. The complete effective exclusion list and changes are recorded. Checkpoint/input hashes and an imported selection JSON's model identity and reviewed=true remain strict requirements.
- Disabling interpolation disables pre-ASR interpolation; disabling both locations disables the global switch. Inapplicable local epoch repair is disabled with an audit.
- Missing/invalid events, unknown conditions, duplicate/out-of-range samples or impossible windows may skip epoch export while continuous processing completes. Inspect epoch_resolution and actual outputs. Continuous completion does not imply epoch export.
- report quality policy is not a promise that every input succeeds. Missing inputs, output collisions, missing dependencies, invalid sampling/filter metadata, missing required coordinates, unusable samples/rank, and damaged/mismatched checkpoints can still stop processing. No guessed data replace such failures.

## Exact ICA rules

threshold: at least one of Muscle, Eye, Heart, Line noise and Channel noise reaches artifact_threshold AND Brain ≤ brain_probability_max. Other is not removed automatically. With a usable real ECG, Heart-only candidates also require maximum absolute Pearson correlation with an ECG channel ≥ heart_min_ecg_correlation. This is an additional AND gate, not independent ECG-only deletion. Without ECG, ICLabel alone is used; no ECG surrogate is constructed.

class_max: remove if Eye equals the maximum class probability; OR Brain ≤0.5 and any of Muscle, Line noise or Channel noise equals that maximum. Ties count. Heart/Other are not independently selected. artifact_threshold, brain_probability_max and ECG support are inactive.

## Epochs and BAD annotations

purpose, task_name and epoch_mode are independent. Both rest and ERP default to continuous output. Explicit events passed to run activate event export when epoch_mode is none. auto QC uses trial-local screening for event epochs under either purpose, and continuous annotations for fixed epochs. Only local repair, not trial-local rejection, requires purpose=erp.

Event-window QC temporarily ignores only newly generated BAD_residual while checking actual event windows for peaks, peak-to-peak and relative noise. Original manual BAD, including pre-existing BAD_residual, still excludes overlapping trials. Continuous samples and annotations remain intact. Ordinary mne.Epochs(clean_raw, reject_by_annotation=True, ...) uses continuous BAD and may not match trial-local exports.

## Advanced ASR options

Pass asr_options as a dictionary. Below are standalone ASRConfig defaults; the pipeline supplies cutoff and min_segment_seconds from asr_cutoff and min_training_seconds. Those two nested keys are ignored with an audit. Invalid nested keys/values use backend defaults. max_memory_mb also affects update boundaries, so it is not a purely cosmetic performance option.
""",
"zh-CN": """
## 依赖处理、自动修正与停止边界

- 未知字段忽略；无效类型、范围与枚举通常恢复所选 purpose/preset 的默认值。每项变化写入 config.adjustments 与 HTML 参数审计。可选配置文件读取失败时仍可使用代码参数。
- 频段受已有采集滤波与 Nyquist 限制；不恢复已丢失频率，不隐式重采样。采样率 ≤80 Hz 时停用当前 ASR；<100 Hz 时停用当前 ICA/ICLabel，均记录原因。
- ICA 关闭则取消复核/人工选择；review 在减除前暂停；无效 manual 列表保留全部成分并要求复核，越界编号被去除，resume 也采用这一规则。完整生效列表与调整均被记录。断点/输入哈希，以及导入选择 JSON 的模型身份和 reviewed=true 仍严格校验。
- 总插值关闭时不执行 ASR 前插值；两处插值均关闭时总开关也关闭。不适用的局部分段修复被关闭并记录。
- 缺失或无效事件、未知条件、重复或越界样本、无法完成的事件窗可跳过分段并继续连续处理；检查 epoch_resolution 及实际输出，连续处理完成不代表已输出试次。
- report 策略仅放宽质量阈值停止规则，不保证所有输入均成功。文件不存在、输出冲突、依赖缺失、无效采集元数据、缺失必要坐标、样本或秩不可用、断点损坏或身份不匹配仍可能停止，不会用猜测数据替代。

## ICA 精确规则

threshold：Muscle、Eye、Heart、Line noise、Channel noise 至少一类达到 artifact_threshold，并且 Brain ≤ brain_probability_max。Other 不自动删除。有可用真实 ECG 时，仅由 Heart 达标的候选还要求与至少一个 ECG 通道的最大绝对 Pearson 相关 ≥ heart_min_ecg_correlation。这是额外 AND 门控，不是单靠 ECG 独立删除。无 ECG 时仅按 ICLabel，不构造替代 ECG。

class_max：Eye 等于该 IC 最大类别概率时删除；或 Brain ≤0.5 且 Muscle、Line noise、Channel noise 中任意一类等于最高概率时删除。并列最高算匹配；不单独删除 Heart/Other；不使用 artifact_threshold、brain_probability_max 或 ECG 相关门控。

## 分段与 BAD

purpose、task_name、epoch_mode 独立。rest 和 ERP 默认都仅输出连续数据；向 run 传显式 events 会在 epoch_mode=none 时开启事件分段。auto QC 对两种 purpose 的事件分段均启用试次局部筛查，对固定窗使用连续标注排除；只有局部修复要求 purpose=erp，单纯试次局部排除不要求。

事件窗 QC 仅暂时忽略本次新增 BAD_residual，按真实事件窗检查峰值、峰峰值与相对噪声。原始人工 BAD，包括原有同名 BAD_residual，仍排除重叠试次。连续数据及标注不因此删除。普通 mne.Epochs(clean_raw, reject_by_annotation=True, ...) 按连续 BAD 排除，不一定与本流程试次局部 QC 的导出结果相同。

## 高级 ASR 参数

通过 asr_options 字典传入。下表为独立 ASRConfig 默认值；流程由 asr_cutoff、min_training_seconds 控制 cutoff、min_segment_seconds。后两个键若写入嵌套选项，会忽略并记录。无效键或值退回后端默认值。max_memory_mb 同时影响更新边界，并非纯性能开关。
"""}

API = {
"en": """
## Runtime API inputs

| Interface | Inputs and returned objects |
|---|---|
| run | raw: continuous MNE BaseRaw; EEG/EOG/ECG in volts; input unchanged. save_path: output directory; subject: safe filename prefix. config/config_file: sources above. montage: explicit geometry override on the working copy; omit it to preserve existing digitization. collect_stages=False avoids extra stage copies. events: integer n×3, first column absolute MNE samples including first_samp. event_id: condition name → integer. epoch_config: stage overrides. invocation: provenance mapping. Additional keywords: all PipelineConfig fields. |
| PipelineResult | raw: cleaned Raw, or None while awaiting ICA review; report: diagnostics dictionary; stages: requested in-memory snapshots; status: run status; outputs: actual product paths. review_required means assess flagged quality before downstream analysis. |
| resume | checkpoint: checkpoint.json; save_path: new output family; subject: optional prefix. Either selection_json or exclude: a complete zero-based list, [] keeps all. reviewer/reason record the decision. original_raw or original_fif supplies matching original data; required explicitly for an in-memory origin or moved source. collect_stages defaults False. Reuses ICA/ICLabel; no change of scientific parameters. |
| render_report | source: PipelineResult or saved HTML; report_path: fresh HTML path. Rebuilds layout using embedded diagnostics, without reprocessing EEG. |
| resolve_config | path: optional JSON path, mapping or PipelineConfig; keyword overrides have highest priority. Returns an immutable PipelineConfig; no configuration file is discovered implicitly. |
| prepare_data | source: supported file or Neuracle directory; output_fif=None returns data only, a path also writes FIF/.events.json/.preparation.json. channel_types and rename are mappings; drop is a channel-name sequence; montage is actual electrode geometry; event_id maps annotation descriptions to integer codes. allow_legacy_uv_per_mm=False applies only to confirmed legacy Neuracle calibration. return_result=False returns Raw; True returns PreparationResult(raw, events, event_id, provenance, outputs). No filtering, referencing or cleaning is performed. |

## Complete CLI flags

Generated from the actual parser. Command: eegproc. Every config field is accessible through repeated --set KEY=JSON, including fields without dedicated flags. JSON uses true/false/null. During --resume, only exclusion/reviewer/reason, original FIF and output arguments are accepted; science settings are frozen. Required input and CLI syntax errors can still stop execution.
""",
"zh-CN": """
## API 运行输入

| 接口 | 输入与返回值 |
|---|---|
| run | raw：连续 MNE BaseRaw，EEG/EOG/ECG 单位 V，输入不变。save_path：输出目录；subject：安全文件名前缀。config/config_file：上述配置来源。montage：显式提供时替换工作副本的电极几何；保留既有实测坐标时请省略。collect_stages=False 避免额外阶段副本。events：n×3 整数数组，第一列为包含 first_samp 的绝对 MNE 样本。event_id：条件名→整数码。epoch_config：分段覆盖。invocation：调用来源字典。其他关键字：全部 PipelineConfig 字段。 |
| PipelineResult | raw：清理后的 Raw，等待 ICA 复核时为 None；report：诊断字典；stages：要求收集的内存快照；status：运行状态；outputs：实际输出路径。review_required 表示后续分析前需判断报告中的质量问题。 |
| resume | checkpoint：checkpoint.json；save_path：新输出位置；subject：可选前缀。selection_json 与 exclude 二选一，后者为完整 0 起始列表，[] 全保留。reviewer/reason 记录人工决策。original_raw 或 original_fif 提供身份匹配的原始数据；内存输入或原文件移动时应显式提供。collect_stages 默认 False。不重复 ICA/ICLabel，不修改科学参数。 |
| render_report | source：PipelineResult 或已有 HTML；report_path：新 HTML 路径。使用内嵌诊断重建布局，不重新处理 EEG。 |
| resolve_config | path：可选 JSON 路径、字典或 PipelineConfig；关键字覆盖优先级最高。返回不可变 PipelineConfig，不隐式查找文件。 |
| prepare_data | source：支持的文件或 Neuracle 目录；output_fif=None 仅返回内存数据，指定路径还输出 FIF/.events.json/.preparation.json。channel_types、rename 为映射；drop 为通道名序列；montage 为实际几何；event_id 为标注描述→整数码。allow_legacy_uv_per_mm=False 仅针对已确认的旧 Neuracle 校准。return_result=False 返回 Raw；True 返回 PreparationResult(raw, events, event_id, provenance, outputs)。不滤波、不参考、不清理。 |

## 全部 CLI 参数

以下内容由实际解析器生成，程序名为 eegproc。全部配置字段均可通过重复 --set KEY=JSON 设置，无须专用 flag；JSON 使用 true/false/null。--resume 只接受选择/复核信息、原始 FIF 与输出，不改变科学配置。必需输入或 CLI 语法错误仍会报错。
"""}


def make_reference(language):
    from eegproc import PipelineConfig, run, resume, render_report, resolve_config
    from eegproc.mne_asr import ASRConfig
    from eegproc.epochs import EpochConfig
    from eegproc.preparation import prepare_data
    from eegproc.cli import parser

    configs = [PipelineConfig(preset=preset, purpose=purpose)
               for preset in ("standard", "eeglab") for purpose in ("rest", "erp")]
    code = '''from dataclasses import asdict
from eegproc import PipelineConfig, run

config = PipelineConfig(purpose="erp", task_name="oddball", epoch_mode="events")
print(asdict(config))
print(config.adjustments)
# result = run(raw, "outputs/sub01", "sub01", config=config, line_frequency=60.)
# Optional JSON is lower priority than these explicit Python keywords:
# result = run(raw, "outputs/sub02", "sub02", config_file="config.json",
#              purpose="rest", task_name="eyes_closed")
'''
    result = INTRO[language].format(count=len(fields(PipelineConfig)))
    result += f"\n{B*3}python\n{code}{B*3}\n\n"
    result += f'{B*3}json\n{{"purpose": "erp", "task_name": "oddball", "epoch_mode": "events"}}\n{B*3}\n\n'
    result += "## 全部流程字段\n\n" if language == "zh-CN" else "## All pipeline fields\n\n"
    result += table(PipelineConfig, DESCRIPTIONS, language, configs) + "\n" + POLICY[language]
    result += "\n" + table(ASRConfig, ASR_DESCRIPTIONS, language)
    result += ("\n\n## 高级分段参数\n\n通过 run 的 epoch_config 传字典或 EpochConfig。完整对象覆盖所有分段默认值，字典仅覆盖给定字段，不修改连续 QC。固定窗强制 tmin=0、tmax=duration−1/sfreq、baseline=None。修复预算/CV 仅 repair_epochs=True 时启用，默认关闭局部修复。下表为独立类默认值；流程继承关系见说明列。\n\n"
               if language == "zh-CN" else
               "\n\n## Advanced epoch parameters\n\nPass a mapping or EpochConfig through run's epoch_config. A complete object overrides all stage defaults; a mapping overrides supplied fields only. Continuous QC is unchanged. Fixed windows force tmin=0, tmax=duration−1/sfreq, baseline=None. Repair budget/CV require repair_epochs=True; repair is off by default. The table shows standalone class defaults; inherited pipeline values are described separately.\n\n")
    result += table(EpochConfig, EPOCH_DESCRIPTIONS, language)
    result += "\n\n"
    for function in (run, resume, render_report, resolve_config, prepare_data):
        result += f"{B*3}text\n{function.__name__}{inspect.signature(function)}\n{B*3}\n\n"
    result += API[language]
    result += "\n| Flags | Destination | Required |\n|---|---|---|\n"
    for action in parser()._actions:
        flags = " / ".join(B + flag + B for flag in action.option_strings)
        result += f"| {flags} | {B}{action.dest}{B} | {bool(action.required)} |\n"
    commands = """eegproc --input-fif prepared/sub01_raw.fif --save-path outputs/sub01 --subject sub01 --purpose erp --task-name oddball --epochs --set report_window_seconds=4.0
eegproc --input-fif prepared/sub02_raw.fif --save-path outputs/sub02 --subject sub02 --purpose rest --asr-cutoff off --set ica_enabled=false
eegproc --resume outputs/review/sub01_ica_review/checkpoint.json --save-path outputs/revised --subject sub01 --ica-exclude 1 4 --original-fif prepared/sub01_raw.fif
"""
    result += f"\n{B*3}bash\n{commands}{B*3}\n"
    result += ("\n### 数据准备命令\n\n" if language == "zh-CN" else "\n### Preparation command\n\n")
    result += f"{B}eegproc-prepare{B}\n\n"
    preparation = [
        ("--input", "Required: recording file or Neuracle folder", "必需：记录文件或 Neuracle 目录"),
        ("--output-fif", "Required: new prepared FIF path", "必需：新的准备后 FIF 路径"),
        ("--montage", "Actual supported montage name; no guessed cap geometry", "实际使用的电极几何名称，不猜测帽型"),
        ("--eog", "Zero or more names to type as EOG", "设为 EOG 的零个或多个通道名"),
        ("--ecg", "Zero or more names to type as ECG", "设为 ECG 的零个或多个通道名"),
        ("--stim", "Zero or more names to type as STIM", "设为 STIM 的零个或多个通道名"),
        ("--drop", "Zero or more channels to omit from prepared input", "准备阶段去除的零个或多个通道"),
        ("--rename-json", "JSON path with old-name to new-name mapping", "旧通道名到新通道名映射的 JSON 路径"),
        ("--event-id-json", "JSON path with annotation-name to code mapping", "标注名称到整数事件码映射的 JSON 路径"),
        ("--neuracle-uv-per-mm", "Opt-in confirmed legacy calibration only", "仅经确认的旧 Neuracle 校准格式启用"),
        ("--help", "Show usage and exit", "显示帮助并退出"),
    ]
    result += "| Flag | Meaning / 说明 |\n|---|---|\n"
    for flag, en, zh in preparation:
        result += f"| {B}{flag}{B} | {zh if language == 'zh-CN' else en} |\n"
    result += ("\n开发者可运行 python scripts/generate_parameter_reference.py 更新本页；--check 检查字段、默认值、API 和 CLI 是否过期。\n"
               if language == "zh-CN" else
               "\nRegenerate with python scripts/generate_parameter_reference.py; --check detects stale fields, defaults, API signatures and CLI definitions.\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for language in ("en", "zh-CN"):
        target = ROOT / "docs" / language / "parameters.md"
        result = make_reference(language)
        if args.check:
            if not target.is_file() or target.read_text(encoding="utf8") != result:
                raise SystemExit(f"Stale generated reference: {target}")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(result, encoding="utf8", newline="\n")
        print(f"{'Checked' if args.check else 'Wrote'} {target.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
