# 完整使用示例

[首页](../../README.zh-CN.md) · [English](../en/usage.md) · [参数说明](parameters.md) · [结果解读](results.md)

[处理流程图](workflow.md) 展示实际处理顺序、分析与 ICA 分支、人工复核路径和产出文件。

示例中的相对路径以启动 Python 时的目录为起点。请按真实记录修改文件路径、通道名称和条件编码。每次运行使用新的输出目录或 subject 标签。

## 可直接执行的示例

安装完成后，在仓库目录执行：

```bash
python examples/synthetic_demo.py --output outputs/demo
python examples/epoch_and_report.py --output outputs/epoch_demo
python examples/analyze_outputs.py --raw outputs/demo/rest/synthetic_cont_raw.fif --output analysis/demo_rest
python examples/analyze_outputs.py --epochs outputs/demo/erp/synthetic_clean-epo.fif --output analysis/demo_erp
```

第一条命令生成 60 秒、32 个 EEG 通道及 EOG/ECG/STIM 的模拟记录，包含事件和人工 BAD，演示静息态、ERP、复核和续处理，不下载外部数据集。其中续处理复用自动建议来演示接口，不代表真的完成了人工复核。后两条命令在独立分析目录生成探索性 PSD、ERP、时频文件；这些是分析示例产物，不是预处理流程额外附件。

实际数据可使用 [code_first.py](../../examples/code_first.py)，其中包含 `rest`、`erp`、`review`、`manual`、`resume`、`config`、`prepare`、`render` 子命令。[batch_process.py](../../examples/batch_process.py) 接收 CSV 清单：

```csv
subject,input_fif,purpose,task_name,events_json
sub01,prepared/sub01_rest_raw.fif,rest,eyes_closed,
sub01,prepared/sub01_task_raw.fif,erp,oddball,prepared/sub01_task_raw.events.json
```

```bash
python examples/batch_process.py manifest.csv --output outputs/cohort --workers 2
python examples/batch_process.py manifest.csv --output outputs/cohort --workers 2 --resume
```

清单路径相对于清单文件，每一行使用独立的 `recording_0001/` 目录。父进程为每份记录启动全新 Python 进程，普通异常、worker 意外退出或超时不影响后续记录。`--workers` 默认为 1，建议从一至两个开始并测量内存峰值；每个 worker 使用 `n_threads=1`。`--timeout` 默认每份记录 86400 秒，超时会一并终止该 worker 及其报告子进程。

worker 在渲染前先保存 EEG 结果和简短的 `batch_result.json` 恢复记录。每条完成后原子更新 `batch_summary.json`，分别记录处理和报告状态。完整报告生成后删除批处理自建的素材包及 worker 日志；报告失败或部分完成时保留素材、日志，不将已完成的 EEG 改为处理失败。

`--resume` 使用**相同清单各行和输出目录**。完整报告直接跳过；延迟、部分完成或失败的报告从 NPZ 生成到新目标，不加载或重做 EEG。此前失败的科学处理仍记录失败，不自动重复；解决原因后使用新输出目录有意重跑。已有不完整文件、但没有恢复记录的目录同样保持原样。只要仍有处理或报告需关注，批量命令就返回非零退出码。Ctrl+C 会终止活动 worker 树、取消排队记录，并保存恢复摘要。

[模拟示例](../../examples/synthetic_demo.py)和[后续分析脚本](../../examples/analyze_outputs.py)也可直接阅读，作为完整 API 用法参考。

## 输入要求与数据准备

`run()` 接收连续的 `mne.io.BaseRaw`，包括 `preload=False` 的文件型 Raw；不会修改传入对象。EEG、EOG、ECG 的样本单位应为 **V**，电极坐标应为 **m**。通道类型、采样率、`first_samp`、测量时间、注释和 montage 应对应实际采集。辅助通道保留，不参与 EEG 清理。应使用设备/MNE 读取器的校准，不能根据“幅度看上去不对”直接猜测倍数。

已经准备好 FIF 时：

```python
import mne
raw = mne.io.read_raw_fif("prepared/sub01_raw.fif", preload=False)
print(raw.info["sfreq"], raw.get_channel_types(), raw.first_samp)
print(raw.annotations)
```

设备文件转换由独立接口完成：

```python
from eegproc.preparation import prepare_data

prepared = prepare_data(
    "device_data/sub01.vhdr",  # 还支持 FIF、EDF、BDF、SET 或 Neuracle 文件夹
    output_fif="prepared/sub01_raw.fif",  # 不填写则只在内存中返回
    channel_types={"VEOG": "eog", "ECG": "ecg"},
    montage="standard_1020",  # 必须与实际帽型及通道名称一致
    return_result=True,
)
raw = prepared.raw
print(prepared.event_id)
```

只填写数据中确实存在的通道名称。已有实测电极坐标时，可不传 `montage`；不要无意中用模板覆盖实测坐标。准备接口也支持改名和删除通道，不做滤波、重参考或去伪迹。设置 `output_fif` 后会输出准备后的 FIF、`.preparation.json` 来源记录和 `.events.json` 事件输入。不传 `return_result=True` 时，直接返回 Raw。

Neuracle 文件夹需要支持的 `data.bdf` 和 `evt.bdf` 文件对，并安装 `device` extra。旧版校准开关只适用于已确认采用相应设备校准约定的记录，不是通用幅度修正参数。

如果已有一个确定以 µV 存储的数组：

```python
import numpy as np
import mne

data_uv = np.load("eeg_microvolts.npy")  # 通道 × 采样点
channel_names = ["Fp1", "Fp2", "F3", "F4", "C3", "C4", "P3", "P4", "O1", "O2"]
info = mne.create_info(channel_names, sfreq=500.0, ch_types="eeg")
raw = mne.io.RawArray(data_uv * 1e-6, info)
raw.set_montage("standard_1020")
raw.save("prepared/sub01_array_raw.fif", fmt="double", overwrite=False)
```

仅在单位、通道顺序和采样率已知时采用此转换。这里用少量通道演示输入构造；通道数本身也会限制 RANSAC、插值、ICA 和事件质控，请查看运行时参数调整和质控提示。

## 静息态

```python
import mne
from eegproc import run

raw = mne.io.read_raw_fif("prepared/sub01_raw.fif", preload=False)
result = run(
    raw,
    save_path="outputs/sub01_rest",
    subject="sub01",
    purpose="rest",
    task_name="eyes_closed",
    line_frequency=50.0,
)
print(result.status)
print(result.outputs)
clean = result.raw
```

默认静息态分析频段为 0.5–80 Hz，ICA 训练为 1–100 Hz，ASR cutoff=20，使用 Picard 和 ICLabel 阈值规则。工频默认 50 Hz，不会自动识别；已知采集环境为 60 Hz 时应指定 `line_frequency=60.0`。

`purpose="rest"` 本身只输出连续数据。若需额外输出无重叠的 2 秒片段：

```python
result = run(
    raw, "outputs/sub01_rest_epochs", "sub01",
    purpose="rest", task_name="eyes_closed",
    epoch_mode="fixed", fixed_epoch_duration=2.0,
    fixed_epoch_overlap=0.0,
)
```

默认 `epoch_qc="auto"` 时，固定片段按连续 BAD 重叠情况拒绝，不做基线校正。片段终点为持续时间减一个采样间隔，因此相邻无重叠片段不会重复终点样本。

## ERP 与显式事件

下面假定原始注释 `"1"` 和 `"2"` 是两个刺激条件。通过显式映射，`"11"`–`"80"` 等试次结束编号不会进入分析。若设备采用 `"Stimulus/S  1"` 等名称，应修改对应映射。

```python
import mne
from eegproc import run

raw = mne.io.read_raw_fif("prepared/sub01_task_raw.fif", preload=False)
events, _ = mne.events_from_annotations(
    raw, event_id={"1": 1, "2": 2},
)
event_id = {"standard": 1, "target": 2}

result = run(
    raw,
    save_path="outputs/sub01_oddball",
    subject="sub01",
    purpose="erp",
    task_name="oddball",
    events=events,
    event_id=event_id,
    epoch_mode="events",
    epoch_qc="event-window",
    epoch_tmin=-0.2,
    epoch_tmax=1.0,
    epoch_baseline=(-0.2, 0.0),
)

if "epochs" in result.outputs:
    epochs = mne.read_epochs(result.outputs["epochs"], preload=True)
    print({name: len(epochs[name]) for name in epochs.event_id})
else:
    print(result.report.get("epoch_resolution"), result.report.get("epochs"))
```

默认 ERP 分析频段为 0.1–30 Hz，仍开启 cutoff=20 的 ASR，ICA 训练频段仍为 1–100 Hz。仅设置 `purpose="erp"` 不会自动分段；传入 `events` 且原 `epoch_mode="none"` 时会启用事件分段。

`events` 为 `(事件数, 3)` 的整数数组，第 0 列是**包含 `raw.first_samp` 的 MNE 绝对采样点**，按时间递增且不能重复；第 2 列为条件编码。`event_id` 是“条件名称→整数编码”，不是“描述→时间”。可选事件缺失或无效时，程序记录原因，跳过分段，继续可执行的连续流程。因此应检查报告，不能仅凭请求参数认定分段已经完成。

若事件存在于 STIM 通道，推荐显式提取：

```python
events = mne.find_events(raw, stim_channel="STI 014", shortest_event=1)
events = mne.pick_events(events, include=[1, 2])
result = run(
    raw, "outputs/sub01_stim", "sub01",
    purpose="erp", task_name="oddball",
    events=events, event_id={"standard": 1, "target": 2},
)
```

也可以设置 `epoch_mode="events", event_source="stim", stim_channel="STI 014"`。当前版本的 `event_source="auto"` 会先尝试注释：若记录中只有 BAD 注释，可能在回退到 STIM 前就遇到提取错误。显式传事件或指定 `event_source="stim"` 可避免这种歧义。采用注释事件时，可指定 `event_source="annotations"`，再用 `event_names` 选择实际存在的条件名。

### 事件窗质控与连续 BAD 的区别

事件窗质控保留输入中的全部人工 BAD。仅对本次自动新增的 `BAD_residual`，分段判断不直接继承其连续时间窗，而是检查真实事件窗内的数据。若输入中原本已有同名 `BAD_residual`，仍然保留并参与拒绝。连续输出本身仍保留完整 BAD 标记和全部采样点。

`epoch_qc="annotations"` 表示直接按连续 BAD 拒绝。`epoch_qc="auto"` 对事件分段采用事件窗质控，对固定片段采用连续注释。默认 `repair_epochs=False`，不合格试次直接拒绝，不做局部插值。可选 `repair_epochs=True` 需要 AutoReject 和 ERP 事件窗质控；有限度修复仅影响导出的 epochs，不覆盖连续数据。修复预算见[参数说明](parameters.md)。

## 独立分段

清理后的 Raw 可直接传给 `epoch()`，既可使用 `run()` 返回的对象，也可重新读取连续 FIF。独立入口与整段流程共用分段质控，不重复去工频、滤波、ASR、ICA 拟合或成分减除，不需要准备后的原始记录。

```python
import mne
from eegproc import epoch

clean = mne.io.read_raw_fif("outputs/sub01/sub01_cont_raw.fif", preload=False)
events, _ = mne.events_from_annotations(clean, event_id={"1": 1, "2": 2})
seg = epoch(
    clean, "outputs/sub01_epochs", "sub01",
    events=events, event_id={"condition_1": 1, "condition_2": 2},
    tmin=-0.2, tmax=1.0, baseline=(-0.2, 0.0),
    epoch_qc="event-window", repair_epochs=False,
)
epochs = seg.epochs
print(seg.status, seg.outputs)
```

仅选择真实刺激条件，不包含试次结束标记。事件仍使用 MNE 绝对样本。也可设置 `event_source="annotations", event_names=("1", "2")` 选择注释条件，或通过 `event_source="stim", stim_channel="STI 014"` 指定实际 STIM 通道。

```python
fixed = epoch(
    clean, "outputs/sub01_fixed", "sub01",
    epoch_mode="fixed", fixed_epoch_duration=2.0, fixed_epoch_overlap=0.0,
)
```

`tmin`、`tmax`、`baseline` 分别是 `epoch_tmin`、`epoch_tmax`、`epoch_baseline` 的短写；原长参数名及科学控制参数继续可用。相关 QC 默认值和全局坏导信息从清理后 Raw 继承，显式设置优先。固定片段不做基线校正。分段保留数据实际滤波频段，不能恢复此前去掉的频率。

新连续 FIF 保存最少的 BAD 来源信息和分段设置，保留原有注释及用户 extras。原有、人工和未知来源 BAD 始终参与拒绝，包括输入已有同名 `BAD_residual`。事件窗模式只重新检查明确标记的自动残留，注释模式拒绝全部 BAD 重叠。旧清理 FIF 没有来源信息时保守处理并提醒。独立分段不依赖原输入；ICA 断点续处理仍需匹配的准备后输入。

`source_report=None` 先查找已读取 `*_cont_raw.fif` 同目录同前缀的 `*_report.html` 或 `*_report_data.npz`，再使用预处理 API 保存的报告路径提示。也可通过 `source_report="outputs/sub01/sub01_report.html"` 手动指定。报告缺失或无法读取时提醒，不阻止分段；已有图像和 ICA 诊断直接复用，只生成新的分段内容。程序不核验报告归属，请选择对应文件。

默认 `keep_source_report=True` 保留原 HTML。设为 `False` 时，仅在新合并 HTML 的 `report_status="completed"` 后删除旧 HTML；部分完成、失败或延迟时保留来源。输出仅为保留的分段 FIF 和一个 HTML 或报告包，不生成 QC JSON、图片／表格附件，不复制连续 Raw 或 ICA。分段请求被跳过或全部拒绝时报告原因，不写空分段文件。

## 即时与延迟报告

`run()`、`epoch()`、`resume()` 均默认 `report=True`。处理进程先采集有限诊断素材，再交给全新 Python 子进程生成 HTML；数值线程环境在子进程导入库之前设置。`report=False` 时只写一个 `*_report_data.npz`，不绘图、不写 HTML。包中包含代表性处理前后波形、频谱摘要、ICA 诊断和 QC 记录，不含整份原始记录。eegproc 的数值采集模块不主动导入 Agg 或字体渲染组件；MNE 自身的操作仍可能导入 Matplotlib。

```python
from eegproc import run, epoch, render_report

prep = run(raw, "outputs/sub01_deferred", "sub01", purpose="erp",
           task_name="oddball", report=False)
seg = epoch(
    prep.raw, "outputs/sub01_deferred_epochs", "sub01",
    events=events, event_id={"standard": 1, "target": 2},
    tmin=-0.2, tmax=1.0, report=False,
)
render_report(prep, "outputs/sub01_deferred/sub01_report.html")
render_report(seg, "outputs/sub01_deferred_epochs/sub01_report.html")
```

后续新会话中，直接传入已保存的数据包：

```python
render_report(
    "outputs/sub01_deferred_epochs/sub01_report_data.npz",
    "outputs/sub01_deferred_epochs/sub01_report.html",
)
```

目标 HTML 必须为新文件。生成报告不会重跑预处理或分段质控，可绘制已保存的诊断素材，但无法恢复从未采集的时间窗。已有 HTML 通过相同的隔离路径复用内嵌图片，来源文件保持不变。

`report_status` 与 `result.status` 分开：`completed` 表示所有适用内容生成完成；`partial` 表示已有 HTML，但存在缺失内容或绘图错误；`failed` 表示报告生成未完成；`deferred` 表示主动延迟 HTML。关闭 ICA 等不适用的内容不计为错误。运行后检查 `result.report["report_status"]`，不要把有无 HTML 用作 EEG 接受或排除规则。

渲染器最多尝试两个全新进程，每次限时 300 秒。意外退出和超时记入 `report_execution`；报告不完整时保留 `outputs["report_data"]` 和 `outputs["report_log"]` 供重试。完整的即时报告会清理临时包和日志。`render_report()` 对完整或部分完成的 HTML 返回路径，生成失败时抛出 `RuntimeError`；仅报告失败不会让 `run()`、`epoch()`、`resume()` 丢失已完成的处理结果。重试素材包时使用新目标文件。进程隔离能够保护调用方免受渲染进程退出影响，不能防止操作系统崩溃。

单份记录的处理进程会与其报告进程短暂共存。选择批量并发数时，应计入额外内存与进程启动开销。

`run()`、`epoch()`、`resume()` 使用相同结果字段：`.raw`、`.epochs`、`.report`、`.outputs`、`.status`。不存在的数据产物为 `None`；整段流程的 `.epochs` 可按需读取已保存 FIF，独立分段通过同一属性返回本次得到的 Epochs。`render_report()` 返回 HTML 路径。[完整生成数据示例](../../examples/epoch_and_report.py) 包含 FIF 重新读取和两阶段延迟报告。

## 通过代码配置

```python
from eegproc import PipelineConfig, resolve_config, run

config = PipelineConfig(
    purpose="erp", task_name="oddball",
    epoch_mode="events", artifact_threshold=0.90,
)
result = run(raw, "outputs/sub01_config", "sub01", config=config,
             events=events, event_id={"standard": 1, "target": 2})

# 字典同样可用；直接关键字参数优先级最高。
parameters = {"purpose": "rest", "task_name": "eyes_open", "line_frequency": 50.0}
resolved = resolve_config(parameters, highpass=1.0, lowpass=100.0)
print(resolved.adjustments)
```

当分析和 ICA 训练频段均为 1–100 Hz 时，流程复用全程频段数据缓冲；算法工作数组和提取有效训练片段仍可能占用额外内存。仅修改分析频段，不会自动把 ICA 训练频段改成相同值。

需要配置文件时，可把 JSON 作为基础：

```python
result = run(
    raw, "outputs/sub01_json", "sub01",
    config_file="configs/rest.json",
    config={"task_name": "eyes_closed"},
    report_window_seconds=4.0,
)
```

优先级为：**预设默认值 < 显式 JSON 文件 < 配置对象/字典 < 直接关键字参数**。不会自动查找配置文件。`None`、`False`、空列表都是明确设置。配置不可原地修改；需要 ERP 默认值时，应重新创建 `PipelineConfig(purpose="erp")`。`dataclasses.replace()` 会保留其他已解析值，不会全部切换到另一套默认值。

无效数值、未知字段和依赖冲突按既定规则自动回退，并记录在 `result.report["parameter_adjustments"]` 及报告 **Summary → Parameter adjustments**。自动回退不代表可以忽略研究参数拼写错误。不可读输入、错误采集元数据、必需依赖缺失、输出冲突和数值处理失败仍会报错。

## ICA 自动剔除规则

| 规则 | 自动删除条件 |
|---|---|
| 默认 `threshold` | Muscle/Eye/Heart/Line noise/Channel noise 中至少一个概率 ≥`artifact_threshold=0.90`，同时 Brain ≤`brain_probability_max=0.20`。Other 不自动删除。 |
| `class_max` | Eye 等于所有类别的最大概率；或者 Muscle/Line noise/Channel noise 等于最大概率且 Brain ≤0.50。并列最大也算。原脚本规则不自动删除 Heart 或 Other。 |

在 `threshold` 下，如果 IC 仅因 Heart 达标而成为候选，且存在可用 ECG，还要求有效训练样本中 IC 与 ECG 的最大绝对 Pearson 相关 ≥0.30。没有可用 ECG 时，单独按 ICLabel 决定。ECG 相关是这些 Heart 候选的附加条件，不是独立增加待删 IC 的通路，也不会自动构造替代 ECG。若该 IC 已独立满足其他伪迹类别阈值，低 ECG 相关不会使其保留。

`class_max` 按原脚本类别逻辑执行，不启用 ECG 辅助；修改 `artifact_threshold` 不会改变其最大类别判定。是否删除还应结合地形图、频谱和激活时间序列，不能只把类别概率当作“脑信号纯度”。

## ICA 人工复核与续处理

### 在减除成分前暂停

```python
import mne
from eegproc import run, resume

raw = mne.io.read_raw_fif("prepared/sub01_raw.fif", preload=False)
pending = run(
    raw, "outputs/sub01_review", "sub01",
    purpose="rest", task_name="eyes_closed", ica_mode="review",
)
assert pending.status == "awaiting_ica_review"
assert pending.raw is None
print(pending.outputs["quality_report"])
```

打开 HTML，所有 IC 均有地形图和直接显示的 PSD。点击地形图可查看激活序列和分类概率。在卡片或详情窗口里都能勾选 **Exclude**，两处选择同步。填写 Reviewer 和 Reason 后，点击 **Download confirmed selection**。

```python
revised = resume(
    pending.outputs["checkpoint"],
    save_path="outputs/sub01_reviewed",
    selection_json="selection.json",
    original_raw=raw,
)
```

勾选框不会立即修改 FIF，也不会重新绘制现有报告。下载的 JSON 是与该模型绑定的完整新排除列表；运行 `resume()` 后才会产生新的清理结果和报告。

续处理目录必须与原输出根目录分离，不能是其本身、子目录或上级目录；使用同级新目录即可。

### 修改已经自动完成的结果，或恢复误删成分

自动运行同样保留未减除 IC 的断点。检查该模型后，传入完整的 **0 起始编号**列表：

```python
revised = resume(
    "outputs/sub01_rest/sub01_ica_review/checkpoint.json",
    "outputs/sub01_revised",
    exclude=[1, 4],  # 仅为格式示例，必须按此模型实际查看后选择
    reviewer="Researcher",
    reason="Reviewed maps, spectra and activation",
    original_fif="prepared/sub01_raw.fif",
)
```

如果旧列表是 `[1, 4, 7]`，新列表改成 `[1, 4]` 就会恢复 IC 7。`exclude=[]` 表示保留全部成分。若希望恢复误删 IC，不应在已清理数据上再次调用减除；应从减除前断点续处理。

初次运行也能传 `ica_mode="manual", ica_exclude=[1, 4]`，但这些编号必须对应本次拟合模型。尚未查看分解时，优先使用 review 模式。

续处理会重做重建、最终插值/参考、连续质控、可选分段和报告，不重新拟合 ICA，不重算 ICLabel、ASR 或滤波。科学参数来自冻结断点；若要修改这些处理参数，应重新开始一轮流程。

保留断点中的三个文件和准备后的原始输入。文件型输入会重开并校验身份；文件移动后传 `original_fif=...`。内存型输入需传未改变的 `original_raw=...`。不能用清理后的结果或另一份记录替代。兼容性检查包括断点格式、计算源码和关键数值依赖，历史断点只能通过已经验证的兼容迁移读取。

## 批处理与内存

短时交互检查可先逐个处理受试者，了解实际内存峰值；无人值守或需要恢复的批次使用前述带监督的 CSV 示例：

```python
from pathlib import Path
import mne
from eegproc import run

summaries = []
for path in sorted(Path("prepared").glob("*_raw.fif")):
    subject = path.name.removesuffix("_raw.fif")
    raw = mne.io.read_raw_fif(path, preload=False)
    result = run(raw, Path("outputs") / subject, subject,
                 purpose="rest", task_name="eyes_closed", n_threads=1)
    summaries.append({"subject": subject, "status": result.status,
                      "report_status": result.report["report_status"],
                      "report": result.outputs.get("quality_report")})
    del result
    raw.close()
```

`preload=False` 降低初始读取负担，但处理阶段仍需内存数组。默认保持 `collect_stages=False`；开启后返回内存中的阶段副本，不额外写阶段文件。若并行处理受试者，每个进程使用独立输出目录，并限制数值线程数；多个任务的内存峰值会叠加。

## 命令行与报告重建

```bash
eegproc --input-fif prepared/sub01_raw.fif --save-path outputs/rest --subject sub01 --purpose rest --task-name eyes_closed
eegproc --input-fif prepared/sub01_task_raw.fif --save-path outputs/erp --subject sub01 --purpose erp --task-name oddball --epochs --events-json prepared/sub01_task_raw.events.json
eegproc --resume outputs/rest/sub01_ica_review/checkpoint.json --ica-exclude 1 4 --save-path outputs/revised --subject sub01 --original-fif prepared/sub01_raw.fif
eegproc-prepare --input device_data/sub01.vhdr --output-fif prepared/sub01_raw.fif --montage standard_1020 --eog VEOG --ecg ECG
eegproc --input-fif prepared/sub01_raw.fif --save-path outputs/deferred --subject sub01 --purpose rest --no-report
eegproc-epoch --input-fif outputs/deferred/sub01_cont_raw.fif --save-path outputs/epochs --subject sub01 --events-json prepared/sub01.events.json --tmin -0.2 --tmax 1.0 --no-report
eegproc-report --source outputs/epochs/sub01_report_data.npz --output outputs/epochs/sub01_report.html
```

`python -m eegproc` 调用同一预处理入口。较少使用的设置可通过 `--set key=JSON` 传入，例如 `--set ica_max_iter=4096`。准备和预处理是两个独立命令。事件 JSON 的结构为 `{"events": [[sample, 0, code], ...], "event_id": {"condition": code}}`；这里是结构示意，省略号不能直接写进真实 JSON。应选择真实刺激条件，不要把试次结束标记当作刺激事件。

重建已有报告界面，或使用前述数据包生成延迟报告：

```python
from eegproc import render_report
render_report("outputs/rest/sub01_report.html", "outputs/rest/sub01_rebuilt_report.html")
```

目标文件必须不存在。该操作复用已保存的图像和诊断，不重新处理 EEG，不改变 IC 选择，也不会更改已有波形图的采样时间窗。
