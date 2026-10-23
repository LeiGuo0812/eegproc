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

```mermaid
flowchart TB
    accTitle: EEG processing stages
    accDescr: Top-down sequence of processing, review decisions, or delivered files.
    DEV["设备文件"] --> PREP["独立数据准备<br/>读取校准、通道类型、电极位置和事件"]
    PREP --> RAW["连续 MNE Raw<br/>SI 单位、原生时间信息、注释和辅助通道"]
    RAW --> RES["解析参数及可选事件请求<br/>检查输入、电极坐标和输出冲突"]
    RES --> EEG["工作副本中选择 EEG<br/>保持原始输入和辅助样本不变"]
    EEG --> LINE["去工频<br/>在此步骤前后立即采集配对频谱"]
    LINE --> CH["在临时训练频段信号上检测坏导<br/>默认先从工作 EEG 排除，最后再插值"]
    CH --> COMMON["重参考及共同频段滤波<br/>共同低端 = 两个高通边界的较小值<br/>共同高端 = 两个低通边界的较大值"]
    COMMON --> GROSS["在 ASR 前标记严重伪迹窗口<br/>默认从 ICA 训练中排除这些窗口"]
    GROSS --> ASR["ASR：静息态和 ERP 默认均开启，cutoff=20<br/>分别处理连续有效片段"]
    ASR --> ENABLED{"是否开启 ICA？"}
    ENABLED -->|是| BRANCH["再次参考；建立分析和训练频段<br/>仅补充所需的额外滤波边界"]
    BRANCH --> ANA["分析信号<br/>静息态：0.5–80 Hz<br/>ERP：0.1–30 Hz"]
    BRANCH --> TRAIN["ICA 训练信号：1–100 Hz<br/>排除输入 BAD、边界和严重伪迹窗口"]
    TRAIN --> ICA["估计秩 → Picard ICA → ICLabel<br/>阈值规则下：可用 ECG 支持 Heart 候选判断"]
    ANA --> CP["保存减除前断点<br/>分析数据 + 冻结 ICA + 续处理记录"]
    ICA --> CP
    CP --> SELECT{"ICA 模式"}
    SELECT -->|auto| AUTO["采用自动排除建议"]
    SELECT -->|manual| MANUAL["采用传入的完整人工排除列表"]
    SELECT -->|review| PAUSE["输出复核 HTML，返回 awaiting_ica_review<br/>通过下方复核流程继续"]
    AUTO --> APPLY["从分析信号中减除选定 IC"]
    MANUAL --> APPLY
    ENABLED -->|否| NOICA["补充所需分析频段滤波"]
    APPLY --> FINAL["重建 EEG 通道<br/>按设置完成最终插值和参考"]
    NOICA --> FINAL
    FINAL --> QC["连续残留质控<br/>添加 BAD_residual 注释，不删除采样点"]
    QC --> SAVE["保存连续 FIF；存在 ICA 时保存最终模型"]
    SAVE --> EPOCH{"请求分段且事件或窗口可用？"}
    EPOCH -->|否| HTML["输出单文件 HTML<br/>实际参数、图片、质控、方法和来源记录"]
    EPOCH -->|是| EQC["分段质控；保留输入人工 BAD<br/>事件分段 + auto：检查真实事件窗<br/>固定分段 + auto：按连续注释拒绝"]
    EQC --> EP["有保留试次时才写 epochs FIF<br/>记录各条件保留率和拒绝原因"]
    EP --> HTML
```

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

```mermaid
flowchart TB
    accTitle: ICA review and continuation
    accDescr: Top-down sequence of processing, review decisions, or delivered files.
    FIT["ICA 已拟合，尚未减除成分"] --> CHECKPOINT["不可变断点<br/>pre_ica_raw.fif + decomposition-ica.fif + checkpoint.json"]
    CHECKPOINT --> MODE{"初次模式"}
    MODE -->|review| REVIEW["复核 HTML<br/>等待选择；result.raw 为 None"]
    MODE -->|auto 或 manual| RESULT["应用初次排除列表<br/>保存清理数据和报告"]
    RESULT --> REVISE["之后希望修改 IC 选择"]
    REVIEW --> UI["查看全部 IC 地形图、图下 PSD 和详情<br/>在卡片或详情中切换 Exclude"]
    REVISE --> UI
    UI --> JSON["下载已确认的 selection.json<br/>0 起始编号的完整排除列表"]
    CHECKPOINT --> VALIDATE["resume：校验断点、模型、源码及依赖版本兼容性<br/>以及准备后的原始输入身份"]
    JSON --> VALIDATE
    LIST["也可直接传 exclude=[...]<br/>exclude=[] 保留全部成分"] --> VALIDATE
    ORIGINAL["准备后的原始 FIF 或未改变的原始 Raw"] --> VALIDATE
    VALIDATE --> LOAD["加载未经 IC 减除的分析数据<br/>以及冻结 ICA 模型"]
    LOAD --> APPLY["应用新的完整排除列表<br/>不再列入的旧删除 IC 会恢复"]
    APPLY --> POST["最终插值/参考 → 连续质控<br/>→ 保存数据/模型 → 可选分段质控 → 新 HTML"]
```

续处理复用原滤波、ASR、ICA 拟合和 ICLabel 结果，并复用父断点，不再复制一份完整断点。仅在 HTML 修改勾选不会改写 FIF；原报告红字和波形仍描述保存时的结果，需创建新一轮结果后才更新。续处理使用独立输出目录。

## 输入与交付文件

```mermaid
flowchart TB
    accTitle: Input and output files
    accDescr: Top-down sequence of processing, review decisions, or delivered files.
    IN["准备后的输入<br/>内存 Raw 或 prepared *_raw.fif"] --> RUN["run"]
    IN -.->|保留以便校验续处理| RESUME["resume"]
    RUN --> CP["*_ica_review/<br/>pre_ica_raw.fif<br/>decomposition-ica.fif<br/>checkpoint.json"]
    CP --> RESUME
    RUN --> CONT["*_cont_raw.fif<br/>清理后连续 EEG + 原辅助通道"]
    RUN --> MODEL["*-ica.fif<br/>模型 + 最终排除列表"]
    RUN --> REPORT["*_report.html<br/>全部图片、表格、参数和来源记录"]
    RUN -->|请求分段且有保留试次| EPO["*_clean-epo.fif"]
    REPORT -.->|复核者下载选择| SEL["selection.json"]
    SEL --> RESUME
    RESUME --> NEW["新的输出目录<br/>连续 FIF + ICA + HTML<br/>可选 epochs FIF"]
```

正常完成且启用 ICA 时通常为**六个文件**：三个结果文件加三个断点文件。保留 epochs 时再加一个。只运行 review 时输出 HTML 和断点；关闭 ICA 时没有模型及断点。大 FIF 可能拆成编号分卷。不生成 `original_raw.fif`、`preview_raw.fif`、逐阶段快照或报告图片/表格附件。`selection.json` 由复核者在需要时手动下载。
