# 后续分析建议

[首页](../../README.zh-CN.md) · [English](../en/analysis.md) · [使用示例](usage.md) · [结果解读](results.md)

从人工接受的结果开始分析，将报告、实际参数和排除决定与分析代码一同保留。下面展示 MNE 的实际操作；频带、电极、时间窗和统计对比应由研究设计确定。流程跑完不能单独证明数据适合研究问题。

## 先选对输出与分析方案

| 目标 | 起点 | 重点选择 |
|---|---|---|
| 静息态 PSD / 频带功率 | 接受的连续 FIF 或固定片段 | 状态、有效时长、BAD 排除、窗长、谱估计方法、参考 |
| ERP | 接受的事件分段 FIF | 事件定义、延迟校正、基线、ROI/时间窗、条件保留率 |
| 时频功率 | 更长且频段适当的事件分段 | 边缘留白、频率/周期数、基线变换、诱发与诱导的定义 |
| 功能连接 | 平稳片段或特定任务 epochs | 参考、传感器混合、估计量、片段数量/长度、空间模型 |
| 源定位 | MNE 数据及头模型/电极位置 | 数字化坐标、配准、参考、秩、协方差 |
| 群体统计 / 解码 | 每个受试者的结果或特征 | 独立统计单位、缺失、多重比较、验证拆分 |

计划比较的记录尽量采用一致流程。两套参数都有科学理由时，可预先设置小规模敏感性分析比较结论，不要根据哪套更容易出现期望效应来选参数。

## 静息态功率谱与频带功率

下面构造不重叠的 4 秒片段，排除全部连续 BAD。Welch 返回 V²/Hz，频率积分后为 V²，乘 `1e12` 得到 µV²。先在受试者内部汇总，再做群体统计。

```python
import mne
import numpy as np
from scipy.integrate import trapezoid

raw = mne.io.read_raw_fif("outputs/sub01_rest/sub01_cont_raw.fif", preload=False)
epochs = mne.make_fixed_length_epochs(
    raw, duration=4.0, overlap=0.0, preload=True,
    reject_by_annotation=True,
)
if len(epochs) == 0:
    raise RuntimeError("No accepted 4-second windows remain")

n_fft = int(round(4.0 * epochs.info["sfreq"]))
spectrum = epochs.compute_psd(
    method="welch", fmin=1.0, fmax=40.0, picks="eeg",
    n_fft=n_fft, n_per_seg=n_fft, n_overlap=0,
)
power, frequencies = spectrum.get_data(return_freqs=True)
alpha = (frequencies >= 8.0) & (frequencies <= 13.0)
broad = (frequencies >= 1.0) & (frequencies <= 40.0)
alpha_uv2 = trapezoid(power[..., alpha], frequencies[alpha], axis=-1) * 1e12
total_uv2 = trapezoid(power[..., broad], frequencies[broad], axis=-1) * 1e12
relative_alpha = np.divide(alpha_uv2, total_uv2,
                           out=np.full_like(alpha_uv2, np.nan), where=total_uv2 > 0)
print("Retained seconds:", len(epochs) * 4.0)
print("Channel-wise median alpha power (µV²):", np.median(alpha_uv2, axis=0))
print("Channel-wise median relative alpha:", np.nanmedian(relative_alpha, axis=0))
spectrum.plot(average=True)
```

相对 alpha 的含义由分母频带决定；把 1–40 Hz 改成别的范围，指标就变了。延长窗长会提高频率分辨率，但也可能减少可保留的完整片段。应同时考虑保留时长、平稳性和估计精度。谱对象和估计方法见 [MNE Spectrum 教程](https://mne.tools/stable/auto_tutorials/time-freq/10_spectrum_class.html)。

直接从 Raw 计算 PSD 时，明确指定 `reject_by_annotation=True` 和适当估计参数。不要把不连续的有效样本直接拼成“连续信号”再滤波或普通 FFT，这会人为制造断点。

## ERP 检查与测量

优先读取导出的 epochs，从而保留本流程事件窗质控的试次选择。若从连续输出重新构造普通 `mne.Epochs`，其默认注释策略会额外使用新生成的连续 BAD，试次集合可能不同。

```python
import mne
import numpy as np

epochs = mne.read_epochs("outputs/sub01_oddball/sub01_clean-epo.fif", preload=True)
conditions = ["standard", "target"]
for name in conditions:
    if name not in epochs.event_id or len(epochs[name]) == 0:
        raise RuntimeError(f"No retained trials for {name}")
print({name: len(epochs[name]) for name in conditions})

evokeds = {name: epochs[name].average(picks="eeg") for name in conditions}
mne.viz.plot_compare_evokeds(evokeds, picks=["Cz", "Pz"], combine="mean")
difference = mne.combine_evoked([evokeds["target"], evokeds["standard"]], weights=[1, -1])

# 仅为格式示例；ROI 和时间窗应按研究设计预先确定。
roi = ["Cz", "Pz"]
interval = (difference.times >= 0.30) & (difference.times <= 0.60)
mean_difference_uv = difference.get_data(picks=roi)[:, interval].mean() * 1e6
print("Target-minus-standard ROI mean (µV):", mean_difference_uv)
```

预先确定窗口中的平均幅度通常比逐个寻找最大峰更容易获得一致测量；这里的 300–600 ms 不是通用 P300 定义。检查基线、单试次分布、事件延迟、头皮分布及各条件样本量。参见 [MNE ERP 教程](https://mne.tools/stable/auto_tutorials/evoked/30_eeg_erp.html)及[分段可视化](https://mne.tools/stable/auto_tutorials/epochs/20_visualize_epochs.html)。

试次数不等意味着精度可能不等，但不必对所有分析都自动丢弃试次凑平数量。根据估计量和对比需要决定是否平衡，并记录抽样种子。不要随意给已做基线校正的 epochs 再换一个基线而不说明原处理。

## 时频分析

默认 −0.2…1.0 秒的 ERP 窗口，常常不足以支撑低频小波和远离边缘的基线。可在预处理时请求更长的事件窗，并确认记录边界、刺激间隔允许这些窗口：

```python
import mne
import numpy as np
from eegproc import run

raw = mne.io.read_raw_fif("prepared/sub01_task_raw.fif", preload=False)
events, _ = mne.events_from_annotations(raw, event_id={"1": 1, "2": 2})
result = run(
    raw, "outputs/sub01_tfr", "sub01", purpose="erp", task_name="oddball",
    events=events, event_id={"standard": 1, "target": 2},
    epoch_tmin=-1.5, epoch_tmax=2.0, epoch_baseline=None,
)
epochs = mne.read_epochs(result.outputs["epochs"], preload=True)
frequencies = np.arange(4.0, 26.0)
power = epochs["target"].compute_tfr(
    method="morlet", freqs=frequencies, n_cycles=frequencies / 2.0,
    picks="eeg", average=True, return_itc=False, n_jobs=1,
)
power.apply_baseline((-0.8, -0.3), mode="logratio")
power.crop(tmin=-0.8, tmax=1.0)
power.plot(picks=["Cz"])
```

这里最高分析频率低于默认 30 Hz 低通。周期数、留白和基线是示例选择，不是流程默认参数。这里先计算每个试次功率再平均，包含诱发及非锁相贡献；“先平均 ERP 再计算功率”是另一种量。若研究诱导功率，应明确其估计方法。参见 [MNE 频率/时频教程](https://mne.tools/stable/auto_tutorials/time-freq/20_sensors_time_frequency.html)。

![短模拟 epochs 的探索性时频展示](../assets/synthetic_time_frequency.png)

这是另一个[脚本示例](../../examples/analyze_outputs.py)的输出，将所有保留的模拟试次在 Pz 汇总，显示相对基线功率的 log10 比值。它使用默认短 ERP 分段，主要演示绘图；边缘效应和短基线限制其科学解释。正式时频分析应采用上面代码一类留出边缘的较长 epochs。此图不是 target 与 standard 的条件差，也不是脑信号恢复验证。

## 功能连接与源定位

MNE-Connectivity 是独立的后续分析软件包，不是 eegproc 运行依赖。使用者可在分析环境中另行安装选定的兼容版本，再分析已接受的 EEG 片段：

```python
# 需要另行安装支持以下 API 的 mne-connectivity 版本。
from mne_connectivity import spectral_connectivity_epochs

connectivity = spectral_connectivity_epochs(
    epochs.copy().pick("eeg"),
    method="wpli2_debiased", mode="multitaper",
    fmin=8.0, fmax=13.0, faverage=True, n_jobs=1,
)
matrix = connectivity.get_data(output="dense")
```

此处 `epochs` 必须是计划分析的片段，例如前面的静息态 epochs，不能误用 notebook 中另一个条件留下的同名变量。应保留足够的平稳片段；片段时长也会改变谱估计。估计方法和假设见[官方 API](https://mne.tools/mne-connectivity/stable/generated/mne_connectivity.spectral_connectivity_epochs.html)。传感器连接仍受混合和参考影响；相位滞后指标不能单独证明解剖或因果连接。

源定位应保留真实电极坐标，考虑平均参考/插值造成的秩变化，并准备适当头模型、配准变换和噪声协方差。模板位置不等于个体数字化位置。上述内容不属于本预处理软件的自动输出，参见 [MNE 正向模型教程](https://mne.tools/stable/auto_tutorials/forward/30_forward.html)。

## 群体统计与解码

被试内对比应先在对齐通道和时间轴后，得到每个受试者的条件差。对受试者差值进行单样本置换检验可保留配对设计；不能把几千个试次当作几千个独立受试者。事先定义电极/时间/频率搜索范围和多重比较方法。簇显著支持簇级结论，不意味着簇中每个时间点都独立显著，也不能据此精确定位效应起点。参见 [MNE 统计推断](https://mne.tools/stable/auto_tutorials/stats-sensor-space/10_background_stats.html)及[单样本簇检验 API](https://mne.tools/stable/generated/mne.stats.permutation_cluster_1samp_test.html)。

解码应按目标泛化单位拆分，例如受试者或会话。特征选择、标准化和学习型变换应在合适的训练折内拟合。整段预处理不能自动保证所有预测问题都不存在信息泄漏，应让预处理与验证方式符合真实使用场景。报告排除受试者、缺失条件、保留时长/试次分布及参数敏感性结果。

## 改变目标滤波范围会怎样？

流程先建立覆盖“分析频段和 ICA 训练频段”的共同频段，在其中进行 ASR，再得到分析和训练分支。因此改变分析频段不一定只影响最后图形：

- 共同频段不变时，ASR 和 ICA 训练输入可能保持可比，但最终幅度、残留 QC 和试次保留仍可能变化。
- 共同频段扩展或低频边界改变时，ASR 校准/重建和后续 ICA 也可能改变。
- 两个频段均为 1–100 Hz 可省去一份全程分支，但也失去较低 ERP 高通对慢成分的保护。另一项模拟综合误差较低，不代表慢 ERP 成分一定保留。
- 提高低通以研究 gamma 会保留更多肌电/工频相关活动；降低低通后，被去掉的高频范围不能再用于分析。

慢 ERP 成分应在提高高通前检查波形、基线和潜伏期影响。频谱分析应考虑滤波过渡带，不能把截止频率当作理想“刀切”边界。已经滤除的信息，后续再滤波无法恢复。参见 [MNE 滤波背景](https://mne.tools/stable/auto_tutorials/preprocessing/25_background_filtering.html)。

比较候选参数时，保持**输入、事件列表、随机种子和预定 QC 规则一致**。同时跟踪有效时长/试次、局部坏导负担、残留伪迹和研究指标。保留各自报告，并在群体假设检验前明确主分析配置。
