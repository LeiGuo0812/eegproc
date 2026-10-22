# 参数参考

[English](../en/parameters.md) · [安装](installation.md) · [使用](usage.md)

本页包含全部 75 个 PipelineConfig 字段，四组默认值由当前代码生成。两种预设遵循同一流程。

## Python 配置方法

优先级：**预设默认值 < 可选 JSON 文件 < config 对象/字典 < run 显式关键字参数**。PipelineConfig 是完整解析后的不可变对象，作为配置源时全部字段均视为显式值。切换目的并重新获取默认值时，应新建配置，而不是只改已有配置的 purpose。

```python
from dataclasses import asdict
from eegproc import PipelineConfig, run

config = PipelineConfig(purpose="erp", task_name="oddball", epoch_mode="events")
print(asdict(config))
print(config.adjustments)
# result = run(raw, "outputs/sub01", "sub01", config=config, line_frequency=60.)
# Optional JSON is lower priority than these explicit Python keywords:
# result = run(raw, "outputs/sub02", "sub02", config_file="config.json",
#              purpose="rest", task_name="eyes_closed")
```

```json
{"purpose": "erp", "task_name": "oddball", "epoch_mode": "events"}
```

## 全部流程字段

| 参数 | 类型 | 有效值 / 单位 | 说明 | standard/rest | standard/erp | eeglab/rest | eeglab/erp |
|---|---|---|---|---|---|---|---|
| `preset` | str | standard / eeglab | 同一流程的参数默认值；eeglab 近似对齐原脚本，不代表 MATLAB 数值复现。 | `'standard'` | `'standard'` | `'eeglab'` | `'eeglab'` |
| `filter_method` | str | mne_fir / eeglab_fir / off | 分析与训练数据的 FIR 实现；off 跳过显式带通滤波。 | `'mne_fir'` | `'mne_fir'` | `'eeglab_fir'` | `'eeglab_fir'` |
| `filter_order` | int | even int ≥ 2; samples | 仅 eeglab_fir 使用；MNE FIR 自行确定滤波长度。 | `15000` | `15000` | `15000` | `15000` |
| `filter_position` | str | after_reference | 目前仅支持在参考处理之后滤波。 | `'after_reference'` | `'after_reference'` | `'after_reference'` | `'after_reference'` |
| `line_method` | str | spectrum_fit / notch / off | 工频方法；spectrum_fit 使用 MNE 多锥窗正弦拟合。 | `'spectrum_fit'` | `'spectrum_fit'` | `'spectrum_fit'` | `'spectrum_fit'` |
| `line_window_seconds` | float | seconds > 0 | spectrum_fit 窗长；不支持的 DPSS 组合恢复 4 秒 / 2 Hz；过短片段记录在报告。 | `4.0` | `4.0` | `4.0` | `4.0` |
| `line_bandwidth` | float | Hz > 0 | 多锥窗带宽；notch/off 时不使用。 | `2.0` | `2.0` | `2.0` | `2.0` |
| `line_p_value` | float | 0 < p < 1 | spectrum_fit 显著性阈值；notch/off 时不使用。 | `0.05` | `0.05` | `0.05` | `0.05` |
| `channel_method` | str | pyprep / eegprep / off | 坏导检测器；eegprep 需可选依赖；off 仍保留输入坏导信息。 | `'pyprep'` | `'pyprep'` | `'eegprep'` | `'eegprep'` |
| `flatline_seconds` | float | seconds > 0 | EEGPrep 兼容检测器的平直时长阈值。 | `5.0` | `5.0` | `5.0` | `5.0` |
| `channel_correlation` | float | 0 < fraction < 1 | EEGPrep 兼容相关阈值，不替代 PyPREP 内部参数。 | `0.8` | `0.8` | `0.8` | `0.8` |
| `channel_broken_fraction` | float | 0 < fraction < 1 | EEGPrep 兼容检测中异常窗口比例。 | `0.4` | `0.4` | `0.4` | `0.4` |
| `reference` | str | average / unchanged | 初始及启用后的最终参考方法；unchanged 均不改变参考。 | `'average'` | `'average'` | `'average'` | `'average'` |
| `interpolate_bads` | bool | bool | 总插值开关；False 同时关闭 ASR 前插值。 | `True` | `True` | `True` | `True` |
| `final_interpolation` | bool | bool | 最终插值，同时受 interpolate_bads 控制。 | `True` | `True` | `True` | `True` |
| `final_reference` | bool | bool | 伪迹处理后应用所选参考；reference=unchanged 时仍不重参考。 | `True` | `True` | `True` | `True` |
| `exclude_gross_from_training` | bool | bool | 将严重伪迹排除出 ICA 训练，不删除最终连续数据样本。 | `True` | `True` | `True` | `True` |
| `residual_qc` | bool | bool | 生成连续 BAD_residual 标注与残留诊断。 | `True` | `True` | `True` | `True` |
| `ica_enabled` | bool | bool | 启用 ICA、ICLabel 与成分处理；False 时复核/人工选择失效。 | `True` | `True` | `True` | `True` |
| `ica_mode` | str | auto / review / manual | auto 应用建议；review 在减除前暂停；manual 应用完整人工列表。 | `'auto'` | `'auto'` | `'auto'` | `'auto'` |
| `ica_exclude` | tuple / None | tuple[int] / None; zero-based | 完整删除列表，0 起始；[] 全保留；auto 下传列表会转 manual；无效或越界编号记录，不用自动建议替代。 | `None` | `None` | `None` | `None` |
| `ica_rule` | str | threshold / class_max | 自动筛选规则见下文；不改变 ICA 拟合。 | `'threshold'` | `'threshold'` | `'class_max'` | `'class_max'` |
| `rank_method` | str | relative / covariance | relative：奇异值大于 max(机器精度容差, 最大奇异值×1e-6)；covariance：矩阵秩与大于 1e-7 µV² 的协方差特征值数的较小值。 | `'relative'` | `'relative'` | `'covariance'` | `'covariance'` |
| `review_author` | str | str | 初次人工决策复核人标签。 | `''` | `''` | `''` | `''` |
| `review_reason` | str | str | 初次人工决策理由。 | `''` | `''` | `''` | `''` |
| `purpose` | str | rest / erp | 分析目的默认值，不单独开启分段。 | `'rest'` | `'erp'` | `'rest'` | `'erp'` |
| `task_name` | str / None | str / None; 1–100 characters | 任务名称元数据，独立于 purpose、文件名和事件筛选；无首尾空格或控制字符。 | `'rest'` | `None` | `'rest'` | `None` |
| `ica_backend` | str | mne | 支持的 ICA 接口；求解器由 ica_method 指定。 | `'mne'` | `'mne'` | `'mne'` | `'mne'` |
| `highpass` | float | Hz > 0; < lowpass | 分析高通边缘，受已有采集滤波限制。 | `0.5` | `0.1` | `0.5` | `0.5` |
| `lowpass` | float | Hz > highpass; < Nyquist | 分析低通边缘，必要时根据输入限制下调。 | `80.0` | `30.0` | `100.0` | `100.0` |
| `training_highpass` | float | Hz > 0; < training_lowpass | ICA 训练高通边缘；分析与训练频段相同时复用滤波信号。 | `1.0` | `1.0` | `0.5` | `0.5` |
| `training_lowpass` | float | Hz > training_highpass; < Nyquist | ICA 训练低通边缘；ICLabel 标准训练频段为 1–100 Hz。 | `100.0` | `100.0` | `100.0` | `100.0` |
| `line_frequency` | float / None | Hz > 0 / None | 已知工频，通常为 50 或 60；处理不超过 min(100, sfreq/2−1) Hz 的谐波；None 关闭，不自动估计。 | `50.0` | `50.0` | `50.0` | `50.0` |
| `artifact_threshold` | float | 0.5 ≤ probability ≤ 1 | 仅 threshold：肌电/眼电/心电/工频/通道噪声中最高概率的最低要求。 | `0.9` | `0.9` | `0.9` | `0.9` |
| `brain_probability_max` | float | 0 ≤ probability ≤ 0.5 | 仅 threshold：删除时允许的 Brain 概率上限。 | `0.2` | `0.2` | `0.2` | `0.2` |
| `asr_cutoff` | float / None | positive / None | 爆发阈值；None 关闭；rest 和 ERP 默认均为 20。 | `20.0` | `20.0` | `20.0` | `20.0` |
| `asr_backend` | str | mne_native | 独立兼容 MNE 的 ASR；运行时不依赖 ASRpy。 | `'mne_native'` | `'mne_native'` | `'mne_native'` | `'mne_native'` |
| `asr_options` | dict / None | dict / None | 高级覆盖见下表；cutoff/min_segment_seconds 使用顶层参数。 | `None` | `None` | `None` | `None` |
| `seed` | int | int; 0 ≤ seed < 2**32 | ICA 与适用的检测/修复阶段的随机种子。 | `20261018` | `20261018` | `20261018` | `20261018` |
| `n_threads` | int | int ≥ 1 | 数值线程数，不自动调度记录级批处理。 | `1` | `1` | `1` | `1` |
| `ica_max_iter` | int | int ≥ 1 | 最大迭代数；报告记录收敛和达到上限情况。 | `1000` | `1000` | `4096` | `4096` |
| `ica_tolerance` | float | positive | Picard tol 或 Infomax w_change；相同数值不代表相同停止行为。 | `1e-07` | `1e-07` | `1e-07` | `1e-07` |
| `bad_channel_fraction_limit` | float | 0 < fraction < 1 | 全局坏导比例质控阈值，由 policy 决定报告或停止。 | `0.3` | `0.3` | `0.3` | `0.3` |
| `bad_channel_policy` | str | auto / report / stop | report 在仍可计算时跑完；stop 在坏导超限时停止；auto 对当前 mne_native 后端等于 report；始终要求至少 8 个可用 EEG 导联。 | `'report'` | `'report'` | `'report'` | `'report'` |
| `min_training_seconds` | float | seconds > 0 | 最短训练与 ASR 片段时长，不代表校准质量已充分。 | `20.0` | `20.0` | `20.0` | `20.0` |
| `gross_peak_uv` | float | µV > 0 | 严重训练伪迹绝对峰值阈值。 | `500.0` | `500.0` | `500.0` | `500.0` |
| `residual_peak_uv` | float | µV > 0 | 残留绝对峰值阈值，也是默认分段阈值。 | `150.0` | `150.0` | `150.0` | `150.0` |
| `residual_ptp_uv` | float | µV > 0 | 残留峰峰值阈值，也是默认分段阈值。 | `200.0` | `200.0` | `200.0` | `200.0` |
| `residual_robust_z` | float | positive robust z | 对数标准差的相对稳健 z 阈值，同时受最小峰峰值限制。 | `6.0` | `6.0` | `6.0` | `6.0` |
| `residual_relative_min_ptp_uv` | float | µV > 0 | 触发相对噪声标准所需最小峰峰值。 | `50.0` | `50.0` | `50.0` | `50.0` |
| `window_seconds` | float | seconds > 0 | 连续严重/残留伪迹筛查窗口。 | `1.0` | `1.0` | `1.0` | `1.0` |
| `guard_seconds` | float | seconds ≥ 0 | 连续伪迹窗口周围扩展时间。 | `0.25` | `0.25` | `0.25` | `0.25` |
| `detect_ransac` | bool | bool | PyPREP RANSAC 开关；需要合适的坐标与导联数量。 | `True` | `True` | `True` | `True` |
| `interpolate_before_asr` | bool | bool | 仅 interpolate_bads=True 时在 ASR 前插值；改变 ASR 空间输入。 | `False` | `False` | `False` | `False` |
| `ica_method` | str | picard / infomax | 使用 Picard 或 MNE Infomax 求解扩展 Infomax 目标。 | `'picard'` | `'picard'` | `'infomax'` | `'infomax'` |
| `heart_min_ecg_correlation` | float | 0 ≤ absolute r ≤ 1 | 仅 threshold：有真实可用 ECG 时对纯 Heart 候选增加 AND 相关门控；无 ECG 时仅用 ICLabel。 | `0.3` | `0.3` | `0.3` | `0.3` |
| `epoch_mode` | str | none / events / fixed | 可选分段；run 显式传 events 时 none 自动改为 events。 | `'none'` | `'none'` | `'none'` | `'none'` |
| `epoch_qc` | str | auto / event-window / annotations | auto 对两种 purpose 的事件分段均用 event-window，对固定窗用 annotations；始终保留原有 BAD。 | `'auto'` | `'auto'` | `'auto'` | `'auto'` |
| `repair_epochs` | bool | bool | 可选 AutoReject 局部修复，仅适用于 ERP 事件窗 QC；需依赖；不改连续样本。 | `False` | `False` | `False` | `False` |
| `epoch_tmin` | float | seconds ≤ 0 | 相对事件起点的分段开始时间。 | `-0.2` | `-0.2` | `-0.2` | `-0.2` |
| `epoch_tmax` | float | seconds > 0 | 相对事件起点的结束时间，端点取整遵循 MNE。 | `1.0` | `1.0` | `1.0` | `1.0` |
| `epoch_baseline` | tuple / None | (start, end) / None; seconds | 位于事件窗内；端点 None 表示边界，整体 None 关闭；固定窗无基线校正。 | `(None, 0.0)` | `(None, 0.0)` | `(None, 0.0)` | `(None, 0.0)` |
| `fixed_epoch_duration` | float | seconds > 0 | 固定窗时长，最后样本时间为 duration − 1/sfreq。 | `2.0` | `2.0` | `2.0` | `2.0` |
| `fixed_epoch_overlap` | float | seconds; 0 ≤ overlap < duration | 固定窗重叠，相邻起点至少差一个样本。 | `0.0` | `0.0` | `0.0` | `0.0` |
| `event_source` | str | auto / annotations / stim | 无显式 events 时使用；仅 STIM 的数据请明确设 stim 或传 events。 | `'auto'` | `'auto'` | `'auto'` | `'auto'` |
| `event_names` | tuple / None | tuple[str] / None | 按 event_id 名称筛选；None 保留映射；未知名称跳过分段并记录。 | `None` | `None` | `None` | `None` |
| `stim_channel` | str / None | str / None | 真实 STIM 通道名；显式事件或标注提取时不用。 | `None` | `None` | `None` | `None` |
| `report_full_record_heatmap` | bool | bool | 可选全程热图；默认关闭以缩小报告。 | `False` | `False` | `False` | `False` |
| `report_waveform_windows` | int | int ≥ 1 | 代表性处理前后波形窗口数量。 | `3` | `3` | `3` | `3` |
| `report_window_seconds` | float | seconds > 0 | 每个代表性波形窗口时长。 | `4.0` | `4.0` | `4.0` | `4.0` |
| `report_max_channels` | int | int ≥ 2 | 代表性波形最多显示通道数。 | `6` | `6` | `6` | `6` |
| `report_dpi` | int | int ≥ 60; dpi | 图片分辨率，越大则 HTML 越大。 | `100` | `100` | `100` | `100` |
| `report_max_width` | int | int ≥ 600; pixels | 报告内图片最大像素宽度。 | `1200` | `1200` | `1200` | `1200` |
| `report_psd_windows` | int | int ≥ 1 | 报告 PSD 抽取的代表性窗口数量上限。 | `30` | `30` | `30` | `30` |
| `report_psd_window_seconds` | float / None | seconds > 0 / None | None 使用内部有界抽样；报告 PSD 用于诊断，不是正式分析估计。 | `None` | `None` | `None` | `None` |

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

| 参数 | 类型 | 有效值 / 单位 | 说明 | 类默认值 |
|---|---|---|---|---|
| `cutoff` | float | positive; use asr_cutoff | 爆发阈值，由顶层控制。 | `20.0` |
| `reference_window` | float | seconds > 0 | 参考段筛选窗口。 | `1.0` |
| `reference_max_bad_channels` | float | 0 ≤ fraction < 1 | 参考窗口坏导比例上限。 | `0.075` |
| `reference_tolerances` | tuple[float, float] | (lo, hi); lo < 0 < hi; lo can be -inf | 稳健参考段接收区间；-inf 用 Python 设置，避免非标准 JSON。 | `(-inf, 5.5)` |
| `calibration_window` | float | seconds > 0 | 校准窗口。 | `0.5` |
| `overlap` | float | 0 ≤ fraction < 1 | 参考与校准窗重叠比例。 | `0.66` |
| `processing_window` | float / None | seconds > 0 / None | 实际窗口=max(指定值或0.5, 1.5×可用EEG导联数/sfreq)。 | `None` |
| `step_size` | int / None | int ≥ 1 / None; samples | None 使用 floor(sfreq×实际处理窗/2)；指定值不能超过处理窗样本数。 | `None` |
| `max_dimensions` | float | 0 < fraction < 1 | 最大重建子空间比例。 | `0.66` |
| `max_memory_mb` | float | MB > 0 | 分块内存预算也影响更新边界与数值结果。 | `64.0` |
| `min_segment_seconds` | float | seconds > 0; use min_training_seconds | 可处理片段最短时长，由顶层控制。 | `20.0` |
| `amplification_limit` | float | positive ratio | 输出/输入 RMS 比值上限；超限以数值不稳定错误停止 ASR。 | `100.0` |

## 高级分段参数

通过 run 的 epoch_config 传字典或 EpochConfig。完整对象覆盖所有分段默认值，字典仅覆盖给定字段，不修改连续 QC。固定窗强制 tmin=0、tmax=duration−1/sfreq、baseline=None。修复预算/CV 仅 repair_epochs=True 时启用，默认关闭局部修复。下表为独立类默认值；流程继承关系见说明列。

| 参数 | 类型 | 有效值 / 单位 | 说明 | 类默认值 |
|---|---|---|---|---|
| `tmin` | float | seconds ≤ 0 | 默认继承解析后的 epoch_tmin。 | `-0.2` |
| `tmax` | float | seconds > 0 | 默认继承解析后的 epoch_tmax。 | `1.0` |
| `baseline` | tuple | tuple / None; seconds | 默认继承 epoch_baseline。 | `(None, 0.0)` |
| `peak_uv` | float | µV > 0 | 默认继承 residual_peak_uv。 | `150.0` |
| `ptp_uv` | float | µV > 0 | 默认继承 residual_ptp_uv。 | `200.0` |
| `robust_z` | float | positive | 默认继承 residual_robust_z。 | `6.0` |
| `relative_min_ptp_uv` | float | µV > 0 | 默认继承 residual_relative_min_ptp_uv。 | `50.0` |
| `max_interpolate` | int | int ≥ 1; channels | 局部插值上限，同时不超过 floor(n_EEG × max_local_fraction)。 | `4` |
| `max_local_fraction` | float | 0 < fraction ≤ 0.25 | 局部插值比例上限。 | `0.125` |
| `min_fit_epochs` | int | int ≥ cv | 拟合 AutoReject 的最少可用试次数。 | `10` |
| `cv` | int | int ≥ 2 | AutoReject 交叉验证折数。 | `5` |
| `seed` | int | int; 0 ≤ seed < 2**32 | 默认继承流程 seed。 | `20261018` |

```text
run(raw: 'mne.io.BaseRaw', save_path: 'str | PathLike[str]', subject: 'str', *, config: 'ConfigInput' = None, config_file: 'str | PathLike[str] | None' = None, montage: 'Any' = None, collect_stages: 'bool' = False, events: 'np.ndarray | Sequence[Sequence[int]] | None' = None, event_id: 'Mapping[str, int] | None' = None, epoch_config: 'EpochConfig | None' = None, invocation: 'Mapping[str, Any] | None' = None, **parameters: 'Any') -> 'PipelineResult'
```

```text
resume(checkpoint: 'str | PathLike[str]', save_path: 'str | PathLike[str]', subject: 'str | None' = None, *, selection_json: 'str | PathLike[str] | None' = None, exclude: 'Sequence[int] | None' = None, reviewer: 'str' = '', reason: 'str' = '', collect_stages: 'bool' = False, original_raw: 'mne.io.BaseRaw | None' = None, original_fif: 'str | PathLike[str] | None' = None) -> 'PipelineResult'
```

```text
render_report(source: 'PipelineResult | str | PathLike[str]', report_path: 'str | PathLike[str]') -> 'Path'
```

```text
resolve_config(path=None, **overrides) -> eegproc.settings.PipelineConfig
```

```text
prepare_data(source, *, output_fif=None, channel_types=None, rename=None, drop=(), montage=None, event_id=None, allow_legacy_uv_per_mm=False, return_result=False)
```


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

| Flags | Destination | Required |
|---|---|---|
| `-h` / `--help` | `help` | False |
| `--input-fif` | `input_fif` | False |
| `--resume` | `resume` | False |
| `--save-path` | `save_path` | True |
| `--subject` | `subject` | True |
| `--preset` | `preset` | False |
| `--ica-mode` | `ica_mode` | False |
| `--ica-exclude` | `ica_exclude` | False |
| `--selection-json` | `selection_json` | False |
| `--review-author` | `review_author` | False |
| `--review-reason` | `review_reason` | False |
| `--original-fif` | `original_fif` | False |
| `--ica-enabled` / `--no-ica-enabled` | `ica_enabled` | False |
| `--interpolate-bads` / `--no-interpolate-bads` | `interpolate_bads` | False |
| `--interpolate-before-asr` / `--no-interpolate-before-asr` | `interpolate_before_asr` | False |
| `--exclude-gross-from-training` / `--no-exclude-gross-from-training` | `exclude_gross_from_training` | False |
| `--residual-qc` / `--no-residual-qc` | `residual_qc` | False |
| `--filter-method` | `filter_method` | False |
| `--filter-position` | `filter_position` | False |
| `--line-method` | `line_method` | False |
| `--channel-method` | `channel_method` | False |
| `--reference` | `reference` | False |
| `--rank-method` | `rank_method` | False |
| `--ica-rule` | `ica_rule` | False |
| `--set` | `settings` | False |
| `--config` | `config` | False |
| `--purpose` | `purpose` | False |
| `--task-name` | `task_name` | False |
| `--highpass` | `highpass` | False |
| `--lowpass` | `lowpass` | False |
| `--artifact-threshold` | `artifact_threshold` | False |
| `--brain-probability-max` | `brain_probability_max` | False |
| `--heart-min-ecg-correlation` | `heart_min_ecg_correlation` | False |
| `--line-frequency` | `line_frequency` | False |
| `--asr-cutoff` | `asr_cutoff` | False |
| `--bad-channel-policy` | `bad_channel_policy` | False |
| `--ica-method` | `ica_method` | False |
| `--seed` | `seed` | False |
| `--n-threads` | `n_threads` | False |
| `--detect-ransac` / `--no-detect-ransac` | `detect_ransac` | False |
| `--epochs` | `epoch_mode` | False |
| `--epoch-mode` | `epoch_mode` | False |
| `--fixed-epochs` | `fixed_epoch_duration` | False |
| `--epoch-qc` | `epoch_qc` | False |
| `--repair-epochs` / `--no-repair-epochs` | `repair_epochs` | False |
| `--event-names` | `event_names` | False |
| `--event-source` | `event_source` | False |
| `--stim-channel` | `stim_channel` | False |
| `--events-json` | `events_json` | False |
| `--tmin` | `epoch_tmin` | False |
| `--tmax` | `epoch_tmax` | False |
| `--baseline` | `baseline` | False |
| `--fixed-overlap` | `fixed_epoch_overlap` | False |
| `--report-full-record-heatmap` / `--no-report-full-record-heatmap` | `report_full_record_heatmap` | False |
| `--report-waveform-windows` | `report_waveform_windows` | False |
| `--report-max-channels` | `report_max_channels` | False |
| `--report-dpi` | `report_dpi` | False |
| `--report-max-width` | `report_max_width` | False |
| `--report-psd-windows` | `report_psd_windows` | False |
| `--report-window-seconds` | `report_window_seconds` | False |
| `--report-psd-window-seconds` | `report_psd_window_seconds` | False |

```bash
eegproc --input-fif prepared/sub01_raw.fif --save-path outputs/sub01 --subject sub01 --purpose erp --task-name oddball --epochs --set report_window_seconds=4.0
eegproc --input-fif prepared/sub02_raw.fif --save-path outputs/sub02 --subject sub02 --purpose rest --asr-cutoff off --set ica_enabled=false
eegproc --resume outputs/review/sub01_ica_review/checkpoint.json --save-path outputs/revised --subject sub01 --ica-exclude 1 4 --original-fif prepared/sub01_raw.fif
```

### 数据准备命令

`eegproc-prepare`

| Flag | Meaning / 说明 |
|---|---|
| `--input` | 必需：记录文件或 Neuracle 目录 |
| `--output-fif` | 必需：新的准备后 FIF 路径 |
| `--montage` | 实际使用的电极几何名称，不猜测帽型 |
| `--eog` | 设为 EOG 的零个或多个通道名 |
| `--ecg` | 设为 ECG 的零个或多个通道名 |
| `--stim` | 设为 STIM 的零个或多个通道名 |
| `--drop` | 准备阶段去除的零个或多个通道 |
| `--rename-json` | 旧通道名到新通道名映射的 JSON 路径 |
| `--event-id-json` | 标注名称到整数事件码映射的 JSON 路径 |
| `--neuracle-uv-per-mm` | 仅经确认的旧 Neuracle 校准格式启用 |
| `--help` | 显示帮助并退出 |

开发者可运行 python scripts/generate_parameter_reference.py 更新本页；--check 检查字段、默认值、API 和 CLI 是否过期。
