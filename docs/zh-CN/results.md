# 结果解读

[首页](../../README.zh-CN.md) · [English](../en/results.md) · [使用示例](usage.md) · [后续分析](analysis.md)

## 输出文件与运行状态

开启 ICA 并正常完成时，通常输出六个文件：

```text
outputs/sub01/
├── sub01_cont_raw.fif          清理后的连续数据，保留原辅助通道
├── sub01-ica.fif               ICA 模型及最终排除列表
├── sub01_report.html           单文件报告，内含图片、表格、参数和来源记录
└── sub01_ica_review/
    ├── pre_ica_raw.fif         分析频段、减除 IC 前的数据及 MNE 容器
    ├── decomposition-ica.fif   冻结分解，exclude=[]
    └── checkpoint.json        参数、事件、输入身份、诊断和续处理状态
```

请求分段且存在保留试次时，另写 `sub01_clean-epo.fif`。全部试次被拒绝时不写空 epochs。review 模式仅输出 HTML 和三个断点文件，尚未形成最终清理数据。关闭 ICA 时不产生 ICA 模型及断点。续处理复用父断点，写新的结果文件。较大 FIF 可能拆成编号分卷，输出清单中的所有分卷都要保留。

不生成 `original_raw.fif`、`preview_raw.fif`、全程训练副本或图片/表格附件。准备后的原始输入应另行保留，因为续处理会核验它。`pre_ica_raw.fif` 是**减除 IC 之前**的恢复点，不是未经滤波的原始数据，也不是整个预处理开始前的数据。

| 状态 / 报告文字 | 含义 | 下一步 |
|---|---|---|
| `completed` / Completed | 完成处理，未触发流程中的复核标记 | 仍需读报告，按研究标准判断可用性。 |
| `review_required` / Completed with observations | 已处理，有质量问题需复核 | 查看观察项，记录接受、修改或排除。 |
| `awaiting_ica_review` / Awaiting ICA selection | ICA 已拟合，尚未减除 | 查看成分后续处理；`result.raw` 为 `None`。 |
| `failed` / Failed | 处理抛出异常 | 查看错误和阶段；部分文件不代表全部完成。 |

记录中另区分处理、交付和报告生成状态。后续报告或分段失败时，前面成功保存的 FIF 可能仍存在。磁盘上有 HTML，不等于全部请求都成功执行。

## 建议按以下顺序读报告

### 1. Summary：先确认记录和实际参数

检查受试者、task_name、分析用途、时长、采样率、EEG 通道数和分析/ICA 频段。任务标签错误属于元数据问题；分析频段错误可能直接改变研究量。阅读 **Parameter adjustments**，尤其关注滤波、分段、缺少可选后端或人工 IC 列表的实际调整。

**Output BAD fraction** 表示被流程综合 BAD/边界掩码覆盖的样本比例，重叠区间不重复计算。**Retained seconds** 是掩码之外的时长，不代表 FIF 被物理裁短。ICA 删除数量是成分数，不是删除导联数，也不是脑信号丢失比例。分段保留率的分母是请求并选中的输入事件，不是原始记录的所有标记。

默认坏导策略为 `report`：完成可执行处理，再报告过高负担供人工判断。默认 30% 坏导上限、残留幅度阈值属于工程质控设置，不是普遍生理标准。另有超过 20% EEG 通道需要全局插值的观察项。应同时看比例、位置和研究问题，不能因为刚好低于某阈值就自动接受。

### 2. EEG preprocessing：波形与总体功率谱

波形图默认最多选三个 **4 秒**窗口：代表性幅度窗、输入峰峰值最大的窗，以及输出峰峰值最大的窗。窗口重合时可能少于三幅。这些是针对性抽样，不等于人工检查了整个记录。

前后使用相同通道和样本。为了可比，显示时均按原来可用 EEG 通道的平均值重参考，并去掉各窗口中位数；该显示操作不改变保存数据。黄色阴影是输入 BAD，红色是输出 BAD，星号表示坏导。重点看跳变是否减轻、最差输出窗口是否仍异常、节律和慢活动是否保留。波形更平不自动代表脑信号恢复更好。

总体 PSD 使用相同的输入有效通道和时间窗。排除输入 BAD，但不会只从“处理后”曲线额外去除新标记的 BAD，否则前后连采样集合也不同。实线为通道中位数，阴影为四分位范围，单位为相对于 µV²/Hz 的 dB。虚线标分析滤波边界，点线标工频。

PSD 时间窗与波形的 4 秒设置相互独立。默认请求时长为 `min(20, max(4, 2 / highpass))` 秒：默认静息态为 4 秒，ERP 为 20 秒；可用片段不足时会缩短。**Signal sampling** 记录实际时间窗和频率分辨率。报告 PSD 是抽样诊断，正式分析应按规定的有效时长重新计算。

### 3. Line-noise removal：区分去工频和后续低通

此图在工频处理前后立即采集，早于带通滤波、ASR 和 ICA，因此能区分工频步骤与后续低通的贡献。前后使用相同通道和短窗，并保留采集参考。

每个目标频率显示附近 ±5 Hz 的频谱，并积分目标 ±1 Hz 范围内的频率格点功率。每个通道先计算 `10*log10(处理前功率/处理后功率)`，再取通道中位数；因此不一定等于表格中两个功率中位数的比值取对数。

- 正值：该频带功率减少。
- 接近零：可测变化小，也可能原先就没有明显工频。
- 负值或邻频变化过大：检查实际处理和采样窗口。

下降量衡量目标附近减少的能量，不证明这些能量全是干扰；还要查看邻近频率及研究是否依赖该窄频带。Disabled、not applied、unavailable 与“下降为零”不同。图下可展开方法、目标频率和采样详情。

### 4. Channels、Annotations 与 ASR

通过通道分布图和 **Channel table** 查看输入坏导、自动检出、插值及最终坏导状态。即使总体比例不高，局部相邻坏导簇也可能影响区域效应。插值是从邻导估计缺失信号，不增加独立空间信息；后续源定位和协方差分析需考虑信号秩。

注释时间线和表格说明问题发生在哪里。**ASR and channel detection** 记录后端诊断、参考/校准信息、分段处理和警告。ASR 重建异常瞬态子空间，不是删除连续采样点。较高修正比例提示检查波形与参考数据，但不是“去除了多少伪迹”或“损失了多少脑信号”的直接百分比。

### 5. ICA：查看全部成分及最终决定

所有拟合成分均以密集地形图排列，PSD 位于图下。**红色成分文字表示保存的结果中已删除该成分。** Pending 表示该分解尚未应用。点击地形图可看激活序列、七类概率及自动建议；概率/决策表区分自动建议与最终决定。

眼动候选可结合额区分布及眨眼/扫视样活动；肌电候选结合周边或局灶分布、高频宽带功率；工频候选看窄频谱峰；心电候选看节律性及实际 ECG 支持记录。这些是人工复核线索，不是新的固定分类器。IC 激活和频谱使用任意成分单位，地形图按各成分归一化，不能由其颜色比较不同 IC 的绝对幅度。

同时查看秩、迭代次数、是否触及迭代上限、训练样本量相对秩平方的比例。分类概率很高也不能补救不稳定的 ICA 分解。显示的成分 PSD/激活来自有限训练预览，并非全程成分活动。

卡片和详情中的 **Exclude** 定义的是下一次排除列表。修改勾选不会改变描述当前保存结果的红字和波形。下载选择文件并[从断点续处理](usage.md)，才会生成新结果。

### 6. Epochs：看各条件损失，而不只看总保留率

柱图和表格分别列出条件输入数、注释/边界拒绝、额外 QC 拒绝及最终保留数。详细事件表保留原事件索引、样本点、条件和拒绝原因。比较条件及受试者间的损失差异；总体保留率较高，也可能存在某个条件选择性损失。

事件窗质控保留输入人工 BAD，对新生成 `BAD_residual` 涉及的试次按真实事件窗重新检查。固定窗默认注释质控则直接使用连续 BAD。可选局部修复单独记录，只改变 epochs。应将保留率与 ERP 波形及残留伪迹一起看，不能单独追求试次数最多。

### 7. Methods、References 与 About

**Methods** 描述实际执行的方法；**References** 给出相关参考；**About** 包括阶段执行、完整实际参数、元数据检查、软件版本、源码哈希、输入输出清单和日志。报告研究方法或比较两轮处理时，应以这些实际记录为准。滤波信息、插值后坏导状态等预期变化，应与事件时间、通道类型或辅助信号意外改变区分。

## 连续 BAD 究竟做了什么？

`BAD_residual` 是对有残留问题的时间段添加注释。它**不删除采样点、不把数据归零，也不额外执行一次去噪**。时间轴、采样点和辅助信号仍然对齐。

后续 MNE 函数决定如何使用标记。普通 `mne.Epochs(..., reject_by_annotation=True)` 会拒绝与 BAD 重叠的试次，不会自动调用 eegproc 的事件窗重新质控。后续 PSD 或分段应明确指定想要的注释策略。接口定义见 [MNE Epochs](https://mne.tools/stable/generated/mne.Epochs.html)。

例如连续窗口及缓冲扩展后，BAD 覆盖 10.0–11.5 秒。一个 9.6–10.8 秒的事件窗与它重叠，普通分段会拒绝。若重叠标记只是此次新增的 `BAD_residual`，eegproc 事件窗模式会改查这段真实试次；若重叠的是输入已有人工 BAD，仍然拒绝。新的试次决定不会擦掉连续输出上的 BAD。

## 人工接受记录

每份数据记录**接受、修改或排除**，注明复核者和理由。优先处理：

1. 校准/元数据或事件时间错误、削波、断点。
2. 最差窗口仍有突变，幅度不合理压低，研究频段附近出现失真。
3. 局部坏导簇、ASR 处理负担大、ICA 不稳定。
4. 混合或不确定 IC，以及类别与 ECG 判断不一致。
5. 有效试次不足、条件损失不均、基线或时间窗不符合任务。
6. 意外元数据不一致，或请求的阶段被跳过。

建议记录字段：`subject, task_name, decision, reviewer, reason, accepted_report, accepted_output, excluded_conditions`。有效时长和最低试次数应按研究设计事先确定，而不是看完条件差异后再调整。

## 从 HTML 读取结构化记录

运行时可直接访问 `result.report`。保存的 HTML 内也嵌入运行记录，无需额外 JSON 文件；下面仅用 Python 标准库读取：

```python
from html.parser import HTMLParser
from pathlib import Path
import json

class RunRecordParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.parts = []
    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("id") == "run-record":
            self.active = True
    def handle_endtag(self, tag):
        if tag == "script":
            self.active = False
    def handle_data(self, data):
        if self.active:
            self.parts.append(data)

parser = RunRecordParser()
parser.feed(Path("outputs/sub01/sub01_report.html").read_text(encoding="utf-8"))
record = json.loads("".join(parser.parts))
print(record["status"], record.get("quality"))
print(record.get("parameter_adjustments", []))
```

报告含记录标签、来源路径和采集元数据。公开分享受试者报告前，应检查这些字段。

## 实际生成的模拟示例

以下图片来自仓库内的[模拟示例](../../examples/synthetic_demo.py)及[分析脚本](../../examples/analyze_outputs.py)，不是受试者数据。本机这次示例中 ERP 保留 17/18 个事件：standard 8/9、target 9/9，模拟输入刻意加入了一段人工 BAD。这用于演示文件处理和试次计数，不是去噪基准，也不是生物学效应量证据。

![模拟静息态结果的 PSD](../assets/synthetic_rest_psd.png)

可看到模拟中设定的振荡峰。细线为单个通道，黑线为平均通道功率；这是后续分析图，与报告中前后配对、通道中位数的 PSD 图定义不同。

![模拟 ERP 两条件平均](../assets/synthetic_condition_erp.png)

图中展示 Pz 条件平均和各条件保留试次数。波形差异与试次数应一起报告；仅看两条曲线的差异，不能衡量相对已知干净真值的恢复精度。
