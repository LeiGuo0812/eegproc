# 处理流程示意图

[首页](../../README.zh-CN.md) · [English](../en/workflow.md) · [使用示例](usage.md) · [参数说明](parameters.md) · [结果解读](results.md)

图示按 `engine.py`、`stages.py`、`signal_ops.py`、`review.py` 和 `delivery.py` 的实际顺序整理。`purpose` 选择参数默认值，整体阶段顺序相同；`task_name` 仅记录任务名称。

| 标准默认参数 | 静息态 | ERP |
|---|---|---|
| 分析频段 | 0.5–80 Hz | 0.1–30 Hz |
| ICA 训练频段 | 1–100 Hz | 1–100 Hz |
| ASR | 开启，cutoff=20 | 开启，cutoff=20 |
| ICA / 自动规则 | Picard / `threshold` | Picard / `threshold` |
| 分段导出 | 需另行请求 | 需另行请求 |

## 主处理流程

### 1. 输入准备与校验

```mermaid
flowchart TB
    accTitle: 输入准备与校验
    accDescr: 准备连续 MNE 输入，解析设置并在清理前校验工作 EEG。
    device_files["设备文件"]
    prepare_input["准备 MNE 输入"]
    raw_input["连续 MNE Raw"]
    validate_input["检查 Raw 输入"]
    resolve_parameters["解析参数"]
    resolve_epochs["解析分段请求"]
    check_output["检查输出路径"]
    copy_input["建立工作副本"]
    check_coordinates["检查 EEG 坐标"]
    select_eeg["选择工作 EEG"]
    device_files --> prepare_input
    prepare_input --> raw_input
    raw_input --> validate_input
    validate_input --> resolve_parameters
    resolve_parameters --> resolve_epochs
    resolve_epochs --> check_output
    check_output --> copy_input
    copy_input --> check_coordinates
    check_coordinates --> select_eeg
```

数据准备由独立脚本完成。输入携带经过校准的 SI 单位、通道类型、电极位置、时间、注释和事件；辅助通道样本保留在原 MNE 容器中。

### 2. 工频与坏导处理

```mermaid
flowchart TB
    accTitle: 工频与坏导处理
    accDescr: 采集去工频前后频谱，处理检测到的坏导并完成共同频段滤波。
    line_before["采集去工频前频谱"]
    clean_line["去除工频"]
    line_after["采集去工频后频谱"]
    detect_bads["检测坏导"]
    early_interpolation{"ASR 前插值？"}
    interpolate_early["插值坏导"]
    exclude_bads["排除坏导"]
    initial_reference["重参考"]
    common_filter["共同频段滤波"]
    gross_mask["标记严重伪迹窗口"]
    line_before --> clean_line
    clean_line --> line_after
    line_after --> detect_bads
    detect_bads --> early_interpolation
    early_interpolation -->|是| interpolate_early
    early_interpolation -->|否，默认| exclude_bads
    interpolate_early --> initial_reference
    exclude_bads --> initial_reference
    initial_reference --> common_filter
    common_filter --> gross_mask
```

坏导检测使用临时训练频段信号。严重伪迹掩码在 ASR 前测量，供 ICA 训练排除使用。

### 3. ASR 与频段准备

```mermaid
flowchart TB
    accTitle: ASR 与频段准备
    accDescr: 在有效片段内独立执行 ASR，再准备分析信号和可选 ICA 训练数据。
    asr_enabled{"开启 ASR？"}
    split_segments["划分有效 ASR 片段"]
    calibrate_asr["逐片段校准 ASR"]
    reconstruct_asr["逐片段重建 ASR"]
    ica_enabled{"开启 ICA？"}
    training_reference["再次重参考"]
    training_band["补充训练频段滤波"]
    analysis_band["补充分析频段滤波"]
    select_training["选择有效训练样本"]
    analysis_only["补充分析频段滤波"]
    asr_enabled -->|是| split_segments
    split_segments --> calibrate_asr
    calibrate_asr --> reconstruct_asr
    reconstruct_asr --> ica_enabled
    asr_enabled -->|否| ica_enabled
    ica_enabled -->|是| training_reference
    training_reference --> training_band
    training_band --> analysis_band
    analysis_band --> select_training
    ica_enabled -->|否| analysis_only
```

开启 ICA 后进入阶段 4；关闭 ICA 后直接进入阶段 6。频段准备仅补充所需的额外滤波边界；分析和训练频段相同时复用全程缓冲。

### 4. ICA 分解与自动建议

```mermaid
flowchart TB
    accTitle: ICA 分解与自动建议
    accDescr: 估计秩、拟合 ICA、分类成分，并在减除任何成分前保存断点。
    estimate_rank["估计训练信号秩"]
    fit_ica["拟合 ICA"]
    classify_ics["运行 ICLabel"]
    propose_exclusions["生成成分排除建议"]
    ecg_support{"适用 ECG 辅助？"}
    check_heart["检查 Heart 与 ECG 相关"]
    save_checkpoint["保存 ICA 断点"]
    estimate_rank --> fit_ica
    fit_ica --> classify_ics
    classify_ics --> propose_exclusions
    propose_exclusions --> ecg_support
    ecg_support -->|是| check_heart
    ecg_support -->|否| save_checkpoint
    check_heart --> save_checkpoint
```

ECG 辅助适用于 `threshold` 规则下存在可用 ECG 的 Heart 单独达标候选。其参考信号在拟合 ICA 前，按相同有效训练样本准备。无可用 ECG 时仅由 ICLabel 决定自动建议。断点保存未经成分减除的分析频段数据及冻结分解模型。

### 5. 成分选择

```mermaid
flowchart TB
    accTitle: ICA 成分选择模式
    accDescr: 采用自动或人工排除列表，或先返回复核报告而不减除成分。
    ica_mode{"ICA 模式"}
    automatic_list["采用自动列表"]
    manual_list["采用完整人工列表"]
    apply_ica["减除选定成分"]
    review_html["写入复核 HTML"]
    await_review(["等待 ICA 复核"])
    ica_mode -->|auto| automatic_list
    ica_mode -->|manual| manual_list
    ica_mode -->|review| review_html
    automatic_list --> apply_ica
    manual_list --> apply_ica
    review_html --> await_review
```

自动和人工模式进入阶段 6。复核模式返回 `awaiting_ica_review`，且 `result.raw` 为 `None`；随后使用下方续处理流程。

### 6. 连续数据交付

```mermaid
flowchart TB
    accTitle: 连续数据完成与交付
    accDescr: 重建 EEG、执行配置的最终操作、标记残留伪迹并保存连续结果。
    rebuild_eeg["重建 EEG 通道"]
    final_interpolation["最终坏导插值"]
    final_reference["最终重参考"]
    restore_container["恢复 MNE 容器"]
    continuous_qc["检查连续残留伪迹"]
    annotate_residual["添加 BAD_residual 注释"]
    save_continuous["保存连续 FIF"]
    model_available{"存在 ICA 模型？"}
    save_model["保存最终 ICA 模型"]
    epoch_stage(["进入阶段 7"])
    rebuild_eeg --> final_interpolation
    final_interpolation --> final_reference
    final_reference --> restore_container
    restore_container --> continuous_qc
    continuous_qc --> annotate_residual
    annotate_residual --> save_continuous
    save_continuous --> model_available
    model_available -->|是| save_model
    model_available -->|否| epoch_stage
    save_model --> epoch_stage
```

插值、参考和残留注释分别遵循对应开关。重建保留原辅助通道及 MNE 元数据；连续质控不删除采样点。

### 7. 可选分段与报告

```mermaid
flowchart TB
    accTitle: 可选分段导出与报告
    accDescr: 运行请求的分段质控，仅在有保留试次时保存，并写入单文件 HTML 报告。
    epochs_available{"请求分段且条件可用？"}
    repair_enabled{"开启分段修复？"}
    repair_epochs["运行有限分段修复"]
    strict_epochs["运行严格分段质控"]
    retained_trials{"存在保留试次？"}
    save_epochs["保存分段 FIF"]
    summarize_retention["汇总试次保留情况"]
    write_html["写入单文件 HTML"]
    epochs_available -->|是| repair_enabled
    epochs_available -->|否| write_html
    repair_enabled -->|是| repair_epochs
    repair_enabled -->|否，默认| strict_epochs
    repair_epochs --> retained_trials
    strict_epochs --> retained_trials
    retained_trials -->|是| save_epochs
    retained_trials -->|否| summarize_retention
    save_epochs --> summarize_retention
    summarize_retention --> write_html
```

当 `epoch_qc="auto"` 时，事件分段使用真实事件窗质控，固定分段使用连续注释拒绝。有限修复是另一条分段路径。两者均保留输入 BAD；报告包括各条件保留情况及拒绝原因。

- 默认共同频段为：**静息态 0.5–100 Hz，ERP 0.1–100 Hz**。去工频位于这次滤波和 ASR 之前，不是只处理最终低通信号。
- 若分析与 ICA 训练频段完全相同，例如均为 **1–100 Hz**，则复用全程频段缓冲；选择有效训练样本和数值计算仍可能需要其他数组。
- ASR 不跨输入 BAD/边界校准或传播状态。短于配置最小长度的片段跳过并记录；`asr_cutoff=None` 可跳过 ASR。
- 每个可处理 ASR 片段独立选择参考数据、校准和重建，默认最小片段为 20 秒。严重伪迹掩码供后面的 ICA 训练排除使用，不是 ASR 额外排除掩码。
- 坏导检测使用剔除输入 BAD/边界后的临时训练频段副本。ICA 训练默认只保留至少 1 秒的有效子段，总有效量至少 20 秒；有限诊断预览只保留在内存，不另存 Raw 文件。
- 可选 `interpolate_before_asr=True` 会改变前段坏导处理方式。参考/插值开关仍生效；`reference="unchanged"` 也会使最终阶段不改变参考。
- 默认 `threshold` 规则下，仅因 Heart 达标的候选在存在可用 ECG 时还需满足 ECG 相关门槛；没有可用 ECG 时单用 ICLabel。`class_max` 按原脚本类别规则执行，不启用 ECG 辅助。
- 事件窗质控保留输入的全部 BAD，包括人工标记及原本已有的 `BAD_residual`；只对本次新增 `BAD_residual` 的重叠情况改查真实试次。连续输出保留这些注释。可选有限局部修复只改变 epochs。

默认质控策略尽量完成可执行处理，再报告问题供人工接受或排除。仅指定 `purpose="erp"` 不会自动请求分段；可选事件缺失时可能跳过分段，但连续处理仍可完成。

## ICA 人工复核与续处理

### 复核成分选择

```mermaid
flowchart TB
    accTitle: 复核 ICA 成分选择
    accDescr: 查看成分地形图和频谱，确认排除列表并将完整选择交给续处理。
    open_report["打开 ICA 报告"]
    inspect_maps["查看成分地形图"]
    inspect_psd["查看成分功率谱"]
    inspect_details["查看成分详情"]
    toggle_exclude["调整 Exclude 勾选"]
    confirm_selection["确认完整选择"]
    download_selection["下载 selection.json"]
    direct_list["直接传入 exclude 列表"]
    call_resume["调用 resume"]
    open_report --> inspect_maps
    inspect_maps --> inspect_psd
    inspect_psd --> inspect_details
    inspect_details --> toggle_exclude
    toggle_exclude --> confirm_selection
    confirm_selection --> download_selection
    download_selection --> call_resume
    direct_list --> call_resume
```

初次减除前或自动/人工运行后，均可使用复核 HTML。每张成分卡片和详情内都可调整 Exclude。下载的 JSON 与 `exclude=[...]` 是两种替代输入；编号从 0 开始，`exclude=[]` 表示保留全部成分。

### 从断点续处理

```mermaid
flowchart TB
    accTitle: 从已校验 ICA 断点续处理
    accDescr: 校验选择及未改变的断点，恢复原数据并应用新的完整排除列表。
    verify_selection["校验选择身份"]
    verify_hashes["校验断点哈希"]
    check_compatibility["检查代码兼容性"]
    load_model["加载冻结 ICA 模型"]
    validate_exclusions["校验排除编号"]
    verify_original["校验原始输入身份"]
    load_pre_ica["加载减除前数据"]
    restore_metadata["恢复原 MNE 容器"]
    apply_selection["减除选定成分"]
    continue_delivery(["从阶段 6 继续"])
    verify_selection --> verify_hashes
    verify_hashes --> check_compatibility
    check_compatibility --> load_model
    load_model --> validate_exclusions
    validate_exclusions --> verify_original
    verify_original --> load_pre_ica
    load_pre_ica --> restore_metadata
    restore_metadata --> apply_selection
    apply_selection --> continue_delivery
```

提供准备后的原始 FIF 或未改变的原始 Raw。兼容性检查包括计算源码及依赖。续处理使用独立输出目录。新列表替代之前的决定，先前删除、但未列入新列表的成分会恢复。

续处理复用原滤波、ASR、ICA 拟合和 ICLabel 结果，并复用父断点，不再复制一份完整断点。仅在 HTML 修改勾选不会改写 FIF；原报告红字和波形仍描述保存时的结果，需创建新一轮结果后才更新。

## 输入与交付文件

### 结果文件

```mermaid
flowchart TB
    accTitle: 交付结果文件
    accDescr: 每个结果文件各占一个节点；请求且保留的分段由连续结果产生。
    completed_run["run 或 resume"]
    continuous_file["*_cont_raw.fif"]
    ica_file["*-ica.fif"]
    report_file["*_report.html"]
    epoch_file["*_clean-epo.fif"]
    completed_run --> continuous_file
    completed_run -->|开启 ICA| ica_file
    completed_run --> report_file
    continuous_file -->|请求且保留| epoch_file
```

连续 FIF 包含清理后的 EEG 及原辅助通道。最终 ICA 模型包括已应用的排除列表。HTML 内嵌全部报告图片、表格、实际参数及来源记录。

### ICA 断点文件

```mermaid
flowchart TB
    accTitle: ICA 断点文件结构
    accDescr: 分别显示三个断点文件；续处理复用该目录。
    checkpoint_directory["*_ica_review/"]
    pre_ica_file["pre_ica_raw.fif"]
    decomposition_file["decomposition-ica.fif"]
    checkpoint_file["checkpoint.json"]
    checkpoint_directory --> pre_ica_file
    checkpoint_directory --> decomposition_file
    checkpoint_directory --> checkpoint_file
```

`pre_ica_raw.fif` 保存 IC 减除前的分析频段信号。`decomposition-ica.fif` 是冻结模型；`checkpoint.json` 记录续处理设置、身份校验及报告数据。

正常完成且启用 ICA 时通常为**六个文件**：三个结果文件加三个断点文件。保留 epochs 时再加一个。只运行 review 时输出 HTML 和断点；关闭 ICA 时没有模型及断点。大 FIF 可能拆成编号分卷。不生成 `original_raw.fif`、`preview_raw.fif`、逐阶段快照或报告图片/表格附件。`selection.json` 由复核者在需要时手动下载。
