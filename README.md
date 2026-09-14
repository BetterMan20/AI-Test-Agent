# AI-Test-Agent

AI 驱动的软件测试智能体：从需求文档自动产出测试用例，并驱动 API / ADB / DB 执行与证据采集。

## 设计管线（5 阶段，贴合测试团队真流程）

```
S1 需求理解 = 需求解析 + 事实抽取（分块+并行，防截断）
S2 需求分析 = 业务模型建模 + 缺口检测
S3 测试设计 = 模块拆分 + 测试点
S4 用例生成 = 场景式链路测试用例
S5 用例评审 = 用例校验(LLM) + 质量评审(规则) + 发布门禁(规则)
```

- LLM 驱动：S1、S2、S3、S4、S5.校验
- 确定性（快速）：S5.质量评审、S5.发布门禁
- 入口：`python main.py` → 读取 `input/` 下需求文档 → 产物输出到 `output/`

## 执行管线

- `execution/planner.py`：TC→Plan 桥（`plan_from_test_case` / `plan_from_dict` / `plan_from_capture`）
- `execution/runner.py`：执行 API / DB / ADB 步骤，采证 + 验证
- `evidence/`：证据采集（request/response/db_snapshot/adb_output/screenshot/logcat）
- `verification/`：6 种断言（status_code/json_path/text_contains/regex/count/db_rows）

## 常用命令

```powershell
python main.py                  # 跑 5 阶段设计管线
.\stop_pipeline.ps1 -DryRun     # 查看管线进程（避免误杀）
.\stop_pipeline.ps1             # 停止管线进程
python tests\demo_real_adb.py   # 真实设备 ADB 演示
```

## 目录速览

- `agents/` 设计管线 5 阶段 9 个 Agent
- `workflow/qa_workflow.py` 5 阶段编排
- `schema/` JSON Schema（全流程）
- `skills/` LLM Skill Prompt（含 tc-to-plan）
- `execution/`、`tools/`、`evidence/`、`verification/` 执行域
- `docs/project_status_report.html` 项目全景说明

## 详细文档

见 [docs/project_status_report.html](docs/project_status_report.html)。