# 安装教程

[首页](../../README.zh-CN.md) · [English](../en/installation.md) · [使用示例](usage.md)

## 1. 选择 Python 并创建环境

完整功能推荐 **64 位 Python 3.12**。标准安装声明支持 Python >=3.11；可选 EEGPrep 0.4.0 要求 Python >=3.12。安装要求与实际完成的平台验证是两件事，已验证范围见[GitHub Actions](https://github.com/LeiGuo0812/eegproc/actions/workflows/tests.yml)。

Windows PowerShell，已安装 Python 3.12 和 Python launcher 时：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
```

使用完整解释器路径，无需修改 PowerShell 执行策略。若系统允许，也可以执行 `.\.venv\Scripts\Activate.ps1` 激活环境。后文中的 `python` 指环境内的解释器；未激活时，请替换为 `.\.venv\Scripts\python.exe`。

Linux 或 macOS，已安装 Python 3.12 时：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
source .venv/bin/activate
```

下面的安装命令由使用者执行，pip 会将所需依赖下载到指定环境。生成 HTML 报告不要求 GPU、MATLAB、EEGLAB 或桌面 Qt 界面库。环境配置原理见 [Python Packaging User Guide](https://packaging.python.org/en/latest/guides/installing-using-pip-and-virtual-environments/)。

## 2. 安装 eegproc

以下方式任选其一。

### 直接从 GitHub 安装

已安装 Git 时：

```bash
python -m pip install "eegproc @ git+https://github.com/LeiGuo0812/eegproc.git"
```

同时安装所有可选运行后端：

```bash
python -m pip install "eegproc[eegprep,autoreject,device] @ git+https://github.com/LeiGuo0812/eegproc.git"
```

默认分支会继续更新。正式研究建议固定版本，将下面的 `REVISION` 替换为选定的发布标签或完整 commit hash，并保存该标识：

```bash
python -m pip install "eegproc @ git+https://github.com/LeiGuo0812/eegproc.git@REVISION"
```

这是从 GitHub 安装，不等于从 PyPI 执行 `pip install eegproc`。语法见 [pip VCS support](https://pip.pypa.io/en/stable/topics/vcs-support/)。

### 下载 ZIP 或克隆源码

在[仓库页面](https://github.com/LeiGuo0812/eegproc)选择 **Code → Download ZIP**，解压后进入包含 `pyproject.toml` 的文件夹。使用 Git 时则执行：

```bash
git clone https://github.com/LeiGuo0812/eegproc.git
cd eegproc
python -m pip install -r requirements.txt
```

requirements 文件会安装本软件及依赖。应从仓库根目录执行，因为其中的 `.` 指当前目录。依赖版本统一维护在 `pyproject.toml`。参见 [pip requirements 格式](https://pip.pypa.io/en/stable/reference/requirements-file-format/)。

| 文件 | 安装内容 | 在仓库根目录的等效命令 |
|---|---|---|
| `requirements.txt` | MNE、独立 ASR、PyPREP、Picard、ICLabel、HTML 报告 | `python -m pip install .` |
| `requirements-eeglab.txt` | 标准功能 + EEGPrep 滤波/坏导检测，用于近似对齐参数 | `python -m pip install ".[eegprep]"` |
| `requirements-autoreject.txt` | 标准功能 + 可选的试次局部插值 | `python -m pip install ".[autoreject]"` |
| `requirements-device.txt` | 标准功能 + Neuracle BDF 准备所需依赖 | `python -m pip install ".[device]"` |
| `requirements-all.txt` | 全部可选运行后端 | `python -m pip install ".[eegprep,autoreject,device]"` |
| `requirements-dev.txt` | 全部运行后端及测试、文档、构建工具 | `python -m pip install ".[dev,eegprep,autoreject,device]"` |

默认 ASR 随 eegproc 提供，不依赖 EEGPrep 或 ASRpy。只有 `repair_epochs=True` 才需要 AutoReject。常规 MNE 文件读取不需要 Neuracle extra。PyTorch 是 ICLabel 的标准依赖，通用安装的下载体积可能较大；若希望专用 CPU 安装，可先按 [PyTorch 平台选择器](https://pytorch.org/get-started/locally/)安装，再安装 eegproc。

### 从 wheel 安装

若发布页面附带 wheel，下载目标版本后安装实际文件：

```bash
python -m pip install eegproc-0.4.0a2-py3-none-any.whl
```

依赖仍由 pip 解析下载。仅复制这个 wheel 到离线电脑并不足够，还需要全部依赖的安装包。

## 3. 验证安装

切换到源码目录之外再执行：

```bash
python -c "import eegproc; print(eegproc.__version__); print(eegproc.__file__)"
python -m eegproc --help
eegproc --help
eegproc-prepare --help
python -m pip check
```

普通安装的 `eegproc.__file__` 应指向当前环境的 `site-packages`。在源码文件夹中导入成功，不能单独证明安装成功。如果命令行找不到 `eegproc`，请激活环境，或使用该环境解释器执行 `python -m eegproc`。

接着运行[静息态示例](usage.md)。导入检查确认依赖可用；首次实际处理还会检查电极坐标、有效数据长度、信号秩和输入元数据。

## 4. 固定环境、升级与开发

为研究保存当前环境版本：

```bash
python -m pip freeze > environment.txt
```

它记录当前安装环境，不是适用于所有平台的通用锁定文件。保留准备后的原始 FIF、完整 ICA 断点和报告。续处理会验证关键数值依赖和计算来源；升级相关软件后，旧断点可能不再兼容。

需要修改源码时，在仓库目录执行：

```bash
python -m pip install -e ".[dev,eegprep,autoreject,device]"
python -B -m pytest tests -q -p no:cacheprovider
python -m build --outdir dist
python -m twine check dist/*
```

构建隔离环境时可能下载构建依赖。发布源码不包含真实记录、历史生成结果和缓存，保留少量软件回归用的模拟 FIF。研究数据应存放在仓库外或已忽略的目录中。

干净环境验证脚本可由安装用户或 CI 执行；它会创建隔离环境并安装依赖：

```bash
python scripts/validate_clean_install.py --wheel dist/eegproc-0.4.0a2-py3-none-any.whl --output validation/clean-default
python scripts/validate_clean_install.py --wheel dist/eegproc-0.4.0a2-py3-none-any.whl --extras eegprep,autoreject,device --output validation/clean-all
```

请使用新的输出目录。`--existing-environment-check` 只用现有环境验证功能，不安装依赖，也不代表干净环境安装通过。实际完成情况以[GitHub Actions](https://github.com/LeiGuo0812/eegproc/actions/workflows/tests.yml)和 GitHub Actions 的真实运行结果为准。

## 常见问题

| 现象 | 处理方式 |
|---|---|
| `No module named eegproc` | 确认安装与运行使用同一 Python，查看 `python -m pip --version`。 |
| Python 3.11 无法安装 EEGPrep | 使用 Python 3.12，或只安装不含该 extra 的标准流程。 |
| pyEDFlib 要求编译器 | wheel 可用性取决于 Python、系统和架构。优先 Python 3.12，并查看 [0.1.42 文件列表](https://pypi.org/project/pyEDFlib/0.1.42/#files)。已有环境能运行不代表新环境一定有 wheel。 |
| 找不到命令 `eegproc` | 激活环境，或使用 `python -m eegproc`。 |
| 缺少电极位置 | 在准备阶段修正名称、类型，并设置与实际采集一致的 montage。 |
| 输出文件已存在 | 使用新的输出目录或 subject 标签，软件不会覆盖已有结果。 |
| ICA 续处理提示不兼容 | 恢复匹配的软件环境、原始输入和完整断点，不要手动改哈希。 |
| 连续数据完成但没有分段文件 | 查看 **Summary → Parameter adjustments** 和 **Epochs**，区分事件缺失、时间窗无效和试次全部拒绝。 |

eegproc 采用 [BSD 3-Clause 许可证](../../LICENSE)，保留的第三方条款见[第三方说明](../THIRD_PARTY_NOTICES.md)。
