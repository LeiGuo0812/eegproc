# EEG preprocessing：完整参数清单

根据 2026-10-22 当前 0.3.1 代码核对。主配置 `PipelineConfig` 共 **75 个字段**；`asr_options` 另有 **10 个高级键**，`EpochConfig` 有 **12 个分段字段**。以下是程序实际支持的接口，没有增加或修改任何默认参数。

主表默认值为 `preset="standard", purpose="rest"`。标准 ERP 仅将 `purpose` 改为 `"erp"`、`task_name` 默认改为 `None`、分析频带改为 **0.1–30 Hz**；ASR 默认仍开启。时间单位为秒、频率为 Hz、幅度阈值为 µV；Raw 本身仍使用 MNE 的 SI 单位（EEG 为 V）。

```python
from eegproc import run, PipelineConfig

config = PipelineConfig(purpose="erp", task_name="oddball",
                        highpass=0.1, lowpass=30.0,
                        epoch_mode="events", epoch_tmin=-0.2, epoch_tmax=1.0)
result = run(raw, "outputs/sub01", "sub01", config=config,
             events=events, event_id={"standard": 1, "target": 2})
# 同样可以直接：run(raw, output, subject, purpose="erp", task_name="oddball", ...)
```

配置优先级：预设默认值 < 显式指定的配置文件 < 配置对象/字典 < 本次代码关键字。完整配置对象包含当时解析出的全部字段值；切换整套用途默认值时重新构造对象。运行时还会根据实际 Raw 检查输入相关限制，最终以报告中的有效配置为准。`None`、`False`、`[]` 是明确值，不等同于未提供。

## 自动解析与修正

Python、JSON 和 CLI 使用同一个参数解析器。已满足类型、依赖、输入与后端数值约束的请求沿用原值，预设声明的默认值不变；以下表格中的类型、范围和条件描述的是**实际生效值**。不满足这些条件的参数或可选分段请求按下表处理，并记录调整或跳过原因。

| 请求情况 | 生效处理 |
|---|---|
| 不支持的选项、错误类型、非有限数值、超出范围 | 采用所选 `preset` / `purpose` 的对应默认值；不会把 Python 字符串 `"false"` 猜成布尔值 |
| 高低通顺序颠倒或区间为空 | 该对频带参数一起回到所选预设默认值 |
| 未知或已退役的主参数 | 忽略该键并记录；不会自动匹配相近拼写 |
| 可选配置文件无法读取、JSON 非法或配置来源类型不支持 | 记录问题，继续使用预设默认值和有效的代码参数；有效的其他配置来源保留 |
| `asr_options` 中未知、非法或与顶层重复的键 | 忽略该键，使用后端默认值或对应顶层值；其他有效高级选项保留 |
| 显式给出 `ica_exclude`，但仍为 `ica_mode="auto"` | 转为 `manual`，按完整名单处理 |
| 人工名单缺失、包含负数或非整数 | 保持人工模式，采用空名单保留全部 IC，并要求人工复核；不会回退到自动剔除 |
| 人工名单有重复索引 | 去重，保留同一选择 |
| 人工索引超出本次 ICA 分解范围 | 丢弃越界索引，保留合法项；无合法项时全保留，仍保持人工选择 |
| `ica_enabled=False` 与 manual/review 同时设置 | ICA 保持关闭；模式调整为 auto、名单清空为 None |
| `interpolate_bads=False`，但要求 ASR 前插值 | 关闭 ASR 前插值；总开关优先 |
| 两个插值阶段都关闭，但总插值开关打开 | 关闭总插值开关 |
| 局部修复与 rest、固定分段或 annotations QC 冲突，或未请求分段 | 关闭不适用的局部修复 |
| 请求频带超出输入采样率或已应用滤波范围 | 在输入可支持范围内调整频带并记录；不重采样，不恢复已丢失的频率 |
| 采样率 <100 Hz，但请求启用 ICA | 关闭本流程的 ICA/ICLabel 阶段并记录；当前 ICLabel 自相关特征实现不支持该范围，不生成替代分类 |
| 采样率 ≤80 Hz，但请求启用当前 ASR 后端 | 关闭 ASR 并记录，因为该后端的频谱整形不支持这一采样率 |
| spectrum_fit 窗长/带宽组合不满足当前采样率与完整记录样本数的数值条件 | 回到 4 秒 / 2 Hz 配对并记录；随后检查各连续段的支持情况 |
| spectrum_fit 窗长换算为样本数发生数值溢出 | 限制为完整记录时长并记录，再检查拟合支持条件 |
| BAD 或采集边界切出的短段无法支持 spectrum_fit | 仅跳过该段工频拟合，保留样本并报告段范围；其他支持段继续处理 |
| 请求事件分段，但缺少可用事件、映射非法、事件重复或超出记录范围 | 跳过本次事件分段，继续连续预处理；报告明确记录原因，不猜测事件时刻或含义 |
| 请求的 ERP 时间窗超过整段记录时长 | 跳过本次事件分段，继续连续预处理；不自动缩短用户的 ERP 时间窗 |
| CLI 显式指定的事件 JSON 缺失、损坏或为空 | 记录并跳过事件分段，继续连续预处理；不会擅自换成 Raw 注释事件 |
| 固定分段同时传入事件数组 | 仍按固定长度分段，忽略额外事件并记录 |
| 基线区间在实际分段采样网格上没有采样点 | 关闭该次分段基线校正并记录，不移动基线区间或伪造采样点 |
| `collect_stages` 不是布尔值 | 回到 False，不额外创建中间阶段的内存副本，并记录 |

参数构造后的调整可从 `config.adjustments` 查看。运行中的完整参数调整记录保存在 `result.report["parameter_adjustments"]`，并直接显示在 HTML 的 **Summary → Parameter adjustments** 表格中，列出原请求、生效值和原因。有效主配置在 `result.report["config"]`；分段实际配置与工频短段跳过记录另行报告。

自动回退的范围是已定义的配置错误、输入限制和可选分段请求，不会忽略所有运行异常。未知 CLI 标志、缺少必填输入、损坏或无法读取的原始数据、无效采集元数据、输出路径冲突、缺失或不兼容的必需依赖，以及算法数值失败仍会明确报错或将本次运行标记为失败。`bad_channel_policy="stop"` 也继续执行用户指定的停止规则。

```python
config = PipelineConfig(purpose="erp", highpass=-1.0, n_threads=0)
assert config.highpass == 0.1 and config.n_threads == 1
for item in config.adjustments:
    print(item["field"], item["requested"], item["effective"], item["reason"])
```

## 主配置：75 个字段

### 基本设置（5）

| 参数 | 标准静息默认 | 含义、选项和条件 |
|---|---|---|
| `preset` | `"standard"` | `standard` / `eeglab`；选择参数预设，流程顺序相同 |
| `purpose` | `"rest"` | `rest` / `erp`；选择用途默认值；ERP 不自动请求分段 |
| `task_name` | `"rest"` | 自定义任务名，如 `eyes_closed`、`oddball`；ERP 默认 `None`；不改变算法或文件名；非空标签最长 100 字符 |
| `seed` | `20261018` | 随机种子，整数 `0 ≤ seed < 2**32` |
| `n_threads` | `1` | 计算线程限制，正整数；不是同时处理被试数 |

### 滤波（7）

| 参数 | 标准静息默认 | 含义、选项和条件 |
|---|---|---|
| `highpass` | `0.5` | 最终分析高通；ERP 默认 `0.1` |
| `lowpass` | `80.0` | 最终分析低通；ERP 默认 `30.0` |
| `training_highpass` | `1.0` | ICA 训练高通 |
| `training_lowpass` | `100.0` | ICA 训练低通 |
| `filter_method` | `"mne_fir"` | `mne_fir` / `eeglab_fir` / `off`；EEGLAB FIR 使用 EEGPrep Python 实现 |
| `filter_order` | `15000` | 只用于 `eeglab_fir`；≥2 的偶数；MNE FIR 不使用此值 |
| `filter_position` | `"after_reference"` | 当前只接受此值，不能据此调整处理顺序 |

生效的两套频带均满足 `0 < highpass < lowpass < sfreq/2`，包括当前实现的关闭滤波模式。标准 100 Hz 训练低通只有采样率大于 200 Hz 且输入实际保留该频带时才能完整实现；否则程序根据输入上限调整并报告，不自动重采样。输入已经高通移除的慢成分无法恢复；因输入限制调整 ICA 训练频带后偏离 1–100 Hz 时，报告要求人工复核 ICLabel 结果。合法的显式训练频带和 EEGLAB 参数预设不会仅因偏离该频带而计作自动参数修正。分析和训练频带相同时共用完整记录缓冲，但算法工作缓冲及剔除坏段后的训练数据仍可能需要内存。

### 工频（5）

| 参数 | 标准静息默认 | 含义、选项和条件 |
|---|---|---|
| `line_method` | `"spectrum_fit"` | `spectrum_fit` / `notch` / `off`；`notch` 为 MNE 零相位 FIR 陷波 |
| `line_frequency` | `50.0` | 工频基频；例如 50 或 60；`None` 关闭；不自动识别 |
| `line_window_seconds` | `4.0` | spectrum_fit 拟合窗，正数 |
| `line_bandwidth` | `2.0` | spectrum_fit 多锥谱带宽，正数 |
| `line_p_value` | `0.05` | spectrum_fit 的检验 p 值门槛，`0 < p < 1` |

处理给定基频及不超过 `min(100, sfreq/2−1)` Hz 的整数谐波。后面三个拟合参数只在 `spectrum_fit` 下影响清理。目前没有 `CleanLine` 选项。

spectrum_fit 还检查 DPSS/COLA 的数值约束：实际窗至少 2 个样本，带宽小于采样率，且 `实际样本数 × 带宽 / (2 × 采样率) ≥ 0.5`。以完整记录为上限检查参数时不满足这些条件，先选用 4 秒 / 2 Hz 的标准配对。随后按每个 BAD 或采集边界分出的片段检查；不支持的片段只跳过拟合并保留数据，不逐段更换参数。所有片段都支持拟合时沿用原来的完整 MNE 调用路径；这些检查没有另设科学意义上的最低记录时长。

### 坏导、插值与参考（12）

| 参数 | 标准静息默认 | 含义、选项和条件 |
|---|---|---|
| `channel_method` | `"pyprep"` | `pyprep` / `eegprep` / `off`；关闭自动检测仍保留输入坏导 |
| `detect_ransac` | `True` | 仅 PyPREP：启用 RANSAC 坏导检测 |
| `flatline_seconds` | `5.0` | 仅 EEGPrep：平线时长门槛，正数 |
| `channel_correlation` | `0.8` | 仅 EEGPrep：通道相关门槛，介于 0 与 1 |
| `channel_broken_fraction` | `0.4` | 仅 EEGPrep：允许不良时段比例，介于 0 与 1 |
| `bad_channel_fraction_limit` | `0.3` | 坏导比例复核门槛；介于 0 与 1 |
| `bad_channel_policy` | `"report"` | `report` 超比例继续并报告；`stop` 超比例停止；`auto` 当前等同 report |
| `reference` | `"average"` | `average` / `unchanged`；控制流程参考操作 |
| `interpolate_bads` | `True` | 总体允许坏导插值 |
| `interpolate_before_asr` | `False` | 是否在 ASR 前插值；开启要求 interpolate_bads=True |
| `final_interpolation` | `True` | 是否在末尾插值；也受总插值开关控制 |
| `final_reference` | `True` | 是否执行末次参考；关掉不会取消前面已做的参考 |

`reference="unchanged"` 时末次参考也不改变数据。开启总插值时，ASR 前或最终至少一个插值位置须启用。`bad_channel_policy="report"` 取消的是坏导比例超限停止；不足 8 个可用 EEG 通道等不可计算情况仍会报错。

### ASR（3）

| 参数 | 标准静息默认 | 含义、选项和条件 |
|---|---|---|
| `asr_cutoff` | `20.0` | ASR 阈值；正数启用，`None` 关闭；rest/ERP 均默认 20 |
| `asr_backend` | `"mne_native"` | 当前只支持此独立 MNE 兼容后端 |
| `asr_options` | `None` | 高级参数字典；None 使用 ASR 内部默认值，允许键见后表 |

### ICA、人工选择与训练（16）

| 参数 | 标准静息默认 | 含义、选项和条件 |
|---|---|---|
| `ica_enabled` | `True` | 是否拟合并应用 ICA；False 时非 auto 模式会调整为 auto，ICA 保持关闭 |
| `ica_backend` | `"mne"` | 当前只支持 MNE 接口 |
| `ica_method` | `"picard"` | `picard` / `infomax`；两者当前都按 extended-Infomax 设置 |
| `ica_max_iter` | `1000` | 最大迭代次数，正整数 |
| `ica_tolerance` | `1e-7` | Picard 的 tol / Infomax 的 w_change，正数 |
| `rank_method` | `"relative"` | `relative` / `covariance`；决定 ICA 分解维度 |
| `ica_rule` | `"threshold"` | `threshold` 概率门槛 / `class_max` 原脚本最高类别规则 |
| `artifact_threshold` | `0.9` | 仅 threshold：伪迹概率下限；允许 `[0.5, 1]` |
| `brain_probability_max` | `0.2` | 仅 threshold：脑概率上限；允许 `[0, 0.5]` |
| `heart_min_ecg_correlation` | `0.3` | 仅 threshold 且有可用 ECG：心电候选绝对相关下限；允许 `[0, 1]` |
| `ica_mode` | `"auto"` | `auto` 自动应用；`review` 保存断点并暂停；`manual` 应用完整人工名单 |
| `ica_exclude` | `None` | 从 0 开始的完整名单；显式名单选用 manual，`[]` 全保留；人工名单缺失或非法时全保留并报告 |
| `review_author` | `""` | 初次运行人工选择的复核者，记录用途 |
| `review_reason` | `""` | 初次运行人工选择的理由，记录用途 |
| `exclude_gross_from_training` | `True` | ICA 训练排除按 gross_peak_uv 检出的粗大伪迹窗 |
| `min_training_seconds` | `20.0` | 共用最短有效时长设置：用于坏导检测数据量、ICA 有效段及 ASR 连续段；不是独立参考数据充分性的保证 |

threshold 模式使用肌电、眼电、心电、工频、通道噪声的共同概率门槛，同时要求脑概率不超过上限。目前不能按类别分别配置五个概率门槛。只有心电类达到伪迹门槛的候选，在有可用 ECG 时还须满足相关门槛；没有可用 ECG 则只用 ICLabel。当前 ECG 辅助是候选确认，不会仅因 ECG 相关高而额外添加 IC。

只有 ICA 阶段实际运行时才准备 ECG 辅助，其内部目标频带为 1–40 Hz；该频带不是单独开放的用户参数。

本版本在采样率低于 100 Hz 时关闭整套 ICA/ICLabel 阶段，依据是当前 ICLabel 自相关特征实现的输入限制；这不是 ICA 数学方法的通用最低采样率。程序不会为通过分类而自动重采样或伪造概率。`80 < sfreq < 100` 时 ASR 仍可独立运行；`sfreq ≤80` 时当前 ASR 后端也关闭。100 Hz、128 Hz 等输入仍可进入 ICA，但训练频带必须受输入上限约束，相关调整与复核要求会进入报告。

class_max：眼电为最高类别即删除；肌电/工频/通道噪声为最高且 Brain≤0.5 才删除；并列最高计入，不按 Heart/Other 删除。该模式不使用上述可调概率阈值及 ECG 门槛。人工完整名单替代自动建议。

relative 的奇异值相对门槛为内部固定值 1e-6（兼顾机器精度）；covariance 采用矩阵秩与 µV² 协方差特征值大于 1e-7 的维数之较小值。当前不提供独立的 n_components 配置。

### 连续质量控制（8）

| 参数 | 标准静息默认 | 含义、选项和条件 |
|---|---|---|
| `gross_peak_uv` | `500.0` | 粗大伪迹绝对幅值门槛，主要用于 ICA 训练排除 |
| `residual_qc` | `True` | 是否添加自动 BAD_residual；False 仍保留原始 BAD |
| `residual_peak_uv` | `150.0` | 残余绝对幅值门槛；默认也传给事件窗 QC |
| `residual_ptp_uv` | `200.0` | 残余峰峰值门槛；默认也传给事件窗 QC |
| `residual_robust_z` | `6.0` | 相对异常 robust-z 门槛；默认也传给事件窗 QC |
| `residual_relative_min_ptp_uv` | `50.0` | 相对异常判定须同时超过的峰峰值下限 |
| `window_seconds` | `1.0` | 连续粗大/残余伪迹检查窗，正数 |
| `guard_seconds` | `0.25` | 连续异常窗两侧扩展保护时间，非负 |

幅度和相对异常阈值均为正数。连续 BAD 是注释，不删除连续样本。事件窗 QC 可用独立 EpochConfig 改变阈值，不必同时改变连续 QC。

### 事件与分段（11）

| 参数 | 标准静息默认 | 含义、选项和条件 |
|---|---|---|
| `epoch_mode` | `"none"` | `none` / `events` / `fixed`；是否按事件或固定长度分段 |
| `epoch_qc` | `"auto"` | `auto` / `event-window` / `annotations` |
| `repair_epochs` | `False` | 显式启用 AutoReject 局部修复；仅 ERP + events + auto/event-window |
| `epoch_tmin` | `-0.2` | 事件前起点，须 ≤0 |
| `epoch_tmax` | `1.0` | 事件后终点，须 >0 |
| `epoch_baseline` | `(None, 0.0)` | 从试次起点到 0 秒做基线；None 关闭；端点须落在试次内 |
| `fixed_epoch_duration` | `2.0` | 固定分段长度 |
| `fixed_epoch_overlap` | `0.0` | 固定分段重叠，`0 ≤ overlap < duration` |
| `event_source` | `"auto"` | `auto` 优先注释、无事件时尝试 STIM；也可指定 annotations/stim |
| `event_names` | `None` | 保留的事件名称列表/元组；None 不额外筛选 |
| `stim_channel` | `None` | STIM 通道名；None 使用 MNE 的通道选择 |

显式传入 events 会将 epoch_mode=none 升为 events，在事件分段模式下优先于自动事件提取；显式选择 fixed 时则忽略额外事件数组并记录。auto QC 对 events 使用 event-window、对 fixed 使用 annotations，与 purpose 无直接绑定。event-window 只忽略本次新加的 BAD_residual，并按实际试次再检查，保留输入原有 BAD；annotations 按连续 BAD 排除重叠试次，不做额外逐试次幅度筛选。固定分段总是 tmin=0、tmax=duration−1/sfreq、baseline=None。

CLI 的 `--events-json` 是显式事件来源：文件不能使用时跳过分段并报告。自动发现的同名 `.events.json` 若内容是有效的空事件列表，则继续从 Raw 注释或 STIM 提取；损坏的自动事件文件则记录错误并跳过分段。基线端点还会按实际采样网格检查：连续时间上合法、但未包含任何采样点的基线区间会关闭基线校正并报告。

### 报告（8）

| 参数 | 标准静息默认 | 含义、选项和条件 |
|---|---|---|
| `report_full_record_heatmap` | `False` | 是否额外绘制全程数据热图 |
| `report_waveform_windows` | `3` | 代表性前后波形窗数，正整数 |
| `report_window_seconds` | `4.0` | 每个波形展示窗长度，正数 |
| `report_max_channels` | `6` | 波形展示通道数上限，整数且 ≥2；实际可更少 |
| `report_dpi` | `100` | 图像 DPI，整数且 ≥60 |
| `report_max_width` | `1200` | 图像宽度上限（像素），整数且 ≥600 |
| `report_psd_windows` | `30` | PSD 代表性窗数上限，正整数；也约束工频诊断采样窗数 |
| `report_psd_window_seconds` | `None` | None 自动取 min(20, max(4, 2/highpass)) 秒；标准静息 4 秒、ERP 20 秒 |

报告参数不改变清理结果。工频诊断的窗长独立于 PSD 展示窗，当前最多 4 秒。以上选项应在 run 之前设置；render_report 复用已有图，不能用来重新绘制不同窗长的数据。

## ASR 高级选项：10 个键

这些键放在 `asr_options={...}`，不能直接作为顶层关键字。

| 键 | 内部默认 | 含义 |
|---|---|---|
| `reference_window` | `1.0` | 参考筛选窗，秒 |
| `reference_max_bad_channels` | `0.075` | 参考窗允许坏导比例，`0 ≤ value < 1` |
| `reference_tolerances` | `(-inf, 5.5)` | 参考筛选的下/上容限；默认下侧不限制 |
| `calibration_window` | `0.5` | 校准窗，秒 |
| `overlap` | `0.66` | 窗重叠比例，`0 ≤ value < 1` |
| `processing_window` | `None` | 有效窗为 max(指定值或0.5, 1.5×EEG通道数/sfreq) 秒 |
| `step_size` | `None` | 更新步长（采样点）；默认 floor(sfreq×有效窗/2)，不得超过有效窗样本数 |
| `max_dimensions` | `0.66` | 最多重建维度比例，严格介于 0 与 1 |
| `max_memory_mb` | `64.0` | 分块预算；会影响计算分块/更新边界，不保证调低后数值不变 |
| `amplification_limit` | `100.0` | 变换后/前 RMS 放大比的数值异常保护上限 |

生效的窗长、内存预算和放大上限为正数。`cutoff` 与 `min_segment_seconds` 使用顶层 `asr_cutoff` 与 `min_training_seconds`；若放入该字典则忽略并记录。默认门槛组可以直接用 `asr_options=None`，无需展开十个键。

```python
config = PipelineConfig(asr_cutoff=20.0,
    asr_options={"reference_window": 1.0, "calibration_window": 0.5})
```

## 独立分段配置：12 个字段

通过 `from eegproc.epochs import EpochConfig` 导入，并作为 `run(..., epoch_config=...)` 参数传入。未提供时，前七项及 seed 由顶层分段/QC/seed 字段生成。提供 `EpochConfig` 对象时是完整分段配置覆盖，不是只覆盖你填写的字段；也可提供字典仅覆盖列出的字段。无效字段回到解析后的分段默认值并记录。固定分段的时间窗/基线仍由 fixed 设置决定。

| EpochConfig 字段 | 构造默认 | 含义 |
|---|---|---|
| `tmin` | `-0.2` | 分段起点 |
| `tmax` | `1.0` | 分段终点 |
| `baseline` | `(None, 0.0)` | 基线区间；None 关闭 |
| `peak_uv` | `150.0` | 试次绝对幅值门槛 |
| `ptp_uv` | `200.0` | 试次峰峰值门槛 |
| `robust_z` | `6.0` | 试次相对异常门槛 |
| `relative_min_ptp_uv` | `50.0` | 相对异常同时要求的峰峰值下限 |
| `max_interpolate` | `4` | 局部修复单次最多插值导数 |
| `max_local_fraction` | `0.125` | 局部修复最多导数比例；有效值 >0 且 ≤0.25 |
| `min_fit_epochs` | `10` | 拟合局部修复所需最少 eligible epochs，须 ≥cv |
| `cv` | `5` | 修复交叉验证折数，有效值 ≥2 |
| `seed` | `20261018` | 分段修复随机种子 |

四个修复控制项只在 repair_epochs=True 时生效。实际插值上限为 `min(max_interpolate, floor(nEEG×max_local_fraction))`。局部修复只修改分段数据，不覆盖连续 Raw。

```python
from eegproc.epochs import EpochConfig
epoch_config = EpochConfig(tmin=-0.2, tmax=0.8, ptp_uv=180.0)
result = run(raw, "outputs/sub01_erp", "sub01", purpose="erp",
             task_name="oddball", epoch_mode="events", epoch_config=epoch_config,
             events=events, event_id={"standard": 1, "target": 2})
```

## run 的运行输入

这些参数属于函数调用，不放进 PipelineConfig。

| 参数 | 默认 | 含义 |
|---|---|---|
| `raw` | 必填 | 连续 MNE Raw，包含正确单位、通道类型、坐标与时间信息 |
| `save_path` | 必填 | 输出目录；既有同名输出会被拒绝覆盖 |
| `subject` | 必填 | 安全文件名前缀；与 task_name 分开 |
| `config` | `None` | PipelineConfig、字典或 JSON 路径 |
| `config_file` | `None` | 可选 JSON 基础配置；先读取此文件，再应用 config 和直接关键字 |
| `montage` | `None` | 显式设置/覆盖电极位置；None 沿用 Raw |
| `collect_stages` | `False` | True 返回中间阶段内存副本、增加内存，不写阶段文件；非法类型回到 False 并记录 |
| `events` | `None` | `(n_events,3)` 整数事件数组，样本号包括 first_samp |
| `event_id` | `None` | 条件名称到整数事件码的映射 |
| `epoch_config` | `None` | 上述 EpochConfig 的完整分段覆盖；字典可只覆盖列出的字段 |
| `invocation` | `None` | 高级溯源映射；一般不用设置，非法类型改用默认 Python API 溯源并记录 |

`**parameters` 接收主表 75 字段的直接关键字。没有“仅保存 HTML”“保存每一阶段”或选择删除原始人工 BAD 的主流程参数；当前固定保存必要结果和 ICA 断点。没有 ECG 通道名配置：先将实际 ECG 通道类型设为 `ecg`，程序自动使用有效通道。

## resume 与报告重建

| resume 参数 | 默认 | 含义 |
|---|---|---|
| `checkpoint` | 必填 | 原 checkpoint.json |
| `save_path` | 必填 | 独立的新输出目录 |
| `subject` | `None` | 输出前缀，None 沿用断点 |
| `selection_json` | `None` | HTML 下载的确认选择文件，与 exclude 二选一 |
| `exclude` | `None` | 完整 0-based 剔除名单；[] 全保留，与 selection_json 二选一 |
| `reviewer` | `""` | 复核者 |
| `reason` | `""` | 复核理由 |
| `collect_stages` | `False` | True 额外返回内存阶段副本；非法类型回到 False 并记录 |
| `original_raw` | `None` | 原输入 Raw，内存输入续处理时提供 |
| `original_fif` | `None` | 原输入 FIF 的新路径，移动原文件后提供 |

续处理不接收新滤波/ASR/ICA 拟合参数；其作用是用同一分解应用新名单。`render_report(source, report_path)` 仅有两个必填输入：已有 PipelineResult 或 HTML、以及新的 HTML 路径。

## 独立数据准备接口

`from eegproc.preparation import prepare_data`。这部分负责输入准备，不属于预处理算法配置。

| prepare_data 参数 | 默认 | 含义 |
|---|---|---|
| `source` | 必填 | Neuracle 文件夹，或 FIF/EDF/BDF/VHDR/SET 文件 |
| `output_fif` | `None` | 可选保存准备后 FIF；指定时还保存准备与事件 JSON |
| `channel_types` | `None` | 如 `{"ECG": "ecg", "HEOG": "eog"}` |
| `rename` | `None` | 通道重命名字典 |
| `drop` | `()` | 明确移除的通道名列表 |
| `montage` | `None` | 实际电极布局/坐标 |
| `event_id` | `None` | 注释到事件码的映射 |
| `allow_legacy_uv_per_mm` | `False` | 仅 Neuracle 目录的旧标定兼容开关 |
| `return_result` | `False` | False 返回 Raw；True 返回含事件、溯源和输出路径的 PreparationResult |

## EEGLAB 参数预设

`preset="eeglab"` 在同一流程中设置下列值，不调用 MATLAB；用户显式传入的参数仍可覆盖它们。

| 参数 | eeglab 预设 |
|---|---|
| `highpass`, `lowpass` | `0.5`, `100.0` |
| `training_highpass`, `training_lowpass` | `0.5`, `100.0` |
| `filter_method` | `"eeglab_fir"` |
| `channel_method` | `"eegprep"` |
| `asr_cutoff` | `20.0` |
| `ica_method` | `"infomax"` |
| `ica_max_iter` | `4096` |
| `rank_method` | `"covariance"` |
| `ica_rule` | `"class_max"` |

其余字段沿用共同默认值；purpose 和 task_name 的用途/命名含义不变。

## 查看实际生效参数

```python
from dataclasses import asdict
from pprint import pprint
from eegproc import PipelineConfig

pprint(asdict(PipelineConfig()))
pprint(asdict(PipelineConfig(purpose="erp")))
pprint(asdict(PipelineConfig(preset="eeglab")))
# 运行后，以 result.report["config"] 查看本次实际生效主配置。
# 所有自动调整：result.report["parameter_adjustments"]。
```

核对来源：[主字段与预设](../eegproc/settings.py)、[自动修正规则](../eegproc/parameter_resolution.py)、[输入相关参数](../eegproc/runtime_parameters.py)、[校验/覆盖/事件规则](../eegproc/configuration.py)、[公共 API](../eegproc/api.py)、[阶段实现](../eegproc/stages.py)、[后端参数作用](../eegproc/backends.py)、[ICA 规则](../eegproc/ica.py)、[ASR 高级字段](../eegproc/mne_asr/api.py)、[EpochConfig](../eegproc/epochs.py)、[数据准备](../eegproc/preparation.py)。
