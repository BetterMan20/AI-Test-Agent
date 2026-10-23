# AI-Test-Agent

AI 驱动的软件测试智能体：从需求文档自动产出**可执行、可复核、可追溯的测试结果**（而非止步于测试用例），并驱动 API / MySQL / ADB / Appium 执行与证据采集。

## 环境准备（先做）

- **必须用仓库虚拟环境里的解释器**：`.venv\Scripts\python.exe`。系统全局 Python 未装
  `jsonschema` 等依赖，直接 `python main.py` 会在 `import engine` 处失败。
- 依赖安装：`.venv\Scripts\python.exe -m pip install -r requirements.txt`
- 跑设计管线前把需求文档放进 `input/`（只放 `.docx/.txt/.md`）；密钥放 `.env`（已 gitignore）。

> 下文命令中的 `python` 均指 `.venv\Scripts\python.exe`。

## 产物分层契约

最终产物不是"测试用例"，而是三层可追溯制品：

```
output/test_design.json     意图层：测试模型/场景/测试点/风险/覆盖 + 用例意图（S3+S4 回填）
output/execution_plan.json  执行层：执行器/参数/前置条件/断言/证据要求（planner --all 汇聚）
output/execution_result.json + output/evidence_*/ + output/defects/
                            结果层：执行结果 + 证据 + 失败缺陷草稿
output/.../execution_report.html + release_gate.json
                            决策层：report.py 聚合 → 人读报告 + Release Gate(GO/GO_WITH_WARNINGS/NO_GO)
```

- `test_cases.json` 降为 S4→S5 的中间形态（评审输入），不再是交付物
- 每条计划携带 `traceability`（test_point/scenario/source_facts），意图→计划→结果可互查
- 失败 TC 自动落 `output/defects/<tc_id>.{json,md}` 草稿（fail=疑似产品缺陷，error=疑似环境问题），人工确认后再提单/PR

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
- `execution/runner.py`：执行 API / DB / ADB / Appium 步骤，采证 + 验证（appium 按 operation 懒启动会话分派）
- `evidence/`：证据采集（request/response/db_snapshot/adb_output/appium_page_source/screenshot/logcat）
- `verification/`：6 种断言（status_code/json_path/text_contains/regex/count/db_rows）

## 报告与决策管线（S7）

- `execution/report.py`：聚合入口——原始数据(JSON/截图/缺陷) → 人读 HTML + 机读 `release_gate.json` + 人工核查清单
- `execution/business_verdict.py`：业务码确定性归因（复现/凭证失效/防重放/限频/业务不符）
- 决策三态：`GO` / `GO_WITH_WARNINGS`（环境归因） / `NO_GO`（fail 或未决缺陷）；runner 收尾自动调用

## 常用命令（按测试阶段分类）

> 状态标注：✅ 已可用 ｜ 🚧 规划中（入口未建，勿直接执行）

### 1️⃣ 探索与建模阶段（S0–S2）

| 命令 | 说明 | 核心产出 | 状态 |
|---|---|---|---|
| `python -m core.qa.run --project higo --domain red_packet_claim --room 14775` | **七阶段全链路探索**：认识→建模→找风险→攻击→验证→回归→学习 | App KB、风险图谱、历史记忆（`knowledge/`、`output/qa/cycle_report.json`） | ✅ |
| `python tests/demo_real_appium.py --drill` | **真机冒烟+下钻**：Appium 混合编排业务下探，验证核心链路连通性 | 实时日志、三件套证据（`output/evidence_appium_chain/`） | ✅ |
| `python tests/demo_real_adb.py` | 真实设备 ADB 演示（对照组） | ADB 证据 | ✅ |

### 2️⃣ 设计与规划阶段（S3–S5）

| 命令 | 说明 | 核心产出 | 状态 |
|---|---|---|---|
| `python main.py` | **意图层设计管线**：读取 `input/` 需求 → S1–S5 五阶段 | `output/test_design.json`（意图层） | ✅ |
| `python execution/planner.py` | **TC→Plan 桥接**：默认取 `output/test_cases.json` 首条 → ExecutionPlan（`--tc-id` 指定） | 单条 ExecutionPlan | ✅ |
| `python -m execution.planner --all --no-llm` | **纯规则计划汇聚**：不经 LLM，TC 批量 → 确定性执行计划 | `output/execution_plan.json`（执行层，meta+plans，带 traceability） | ✅ |

### 3️⃣ 执行与攻击阶段（S6）

| 命令 | 说明 | 核心产出 | 状态 |
|---|---|---|---|
| `python execution/runner.py [cap] [ep] [serial]` | **单场景批量执行**：默认发红包场景（示例 `D:/higo-api send_red_packet emulator-5554`） | `output/evidence_batch_regression/`（日志、截图、XML、execution_result.json） | ✅ |
| `python execution/runner.py --plan-file output/execution_plan.json` | **按计划直读执行**：跳过 TC→Plan 派生，失败自动落缺陷草稿 | `execution_result.json` + `output/defects/<tc_id>.{json,md}` | ✅ |
| `python execution/runner.py ... --appium` | 同上用 Appium 做 UI 业务自动化（替换 ADB dump 面板步骤） | Appium 三件套证据 | ✅ |
| `python -m orchestrator.run_strategy --mode regression` | **分层决策执行**：业务/攻击/稳定性三层解耦回归 | 分层执行结果集 | ✅ |
| `python -m stability.runner --events 40` | **稳定性专项**：状态感知随机 + Crash/ANR 监控 | 稳定性监控数据 | ✅ |
| `python -m projects.a.adapters.mic_fill --count 500 --threads 10` | **房间灌人+占满麦位**：批量登录(未注册自动注册，每账户独立 h_did)→进房1096→补占空麦位；编排引擎在 core/load.py | `output/evidence_a_micfill/roomload_bulk_*.json` | ✅ |

### 4️⃣ 报告与决策阶段（S7）

| 命令 | 说明 | 核心产出 | 状态 |
|---|---|---|---|
| `python -m execution.report [result.json]` | **报告聚合入口**：原始数据(JSON/截图/缺陷) → 人读 HTML + 机读 Release Gate + 人工核查清单（runner 收尾已自动调用） | `execution_report.html` + `release_gate.json`（GO / GO_WITH_WARNINGS / NO_GO） | ✅ |
| `python -m report.generator --input <json> --type deep_diagnosis` | **单点深度诊断报告**：含根因、证据链、风险分级 | Bug 深度诊断报告 | 🚧 规划中 |
| `python -m report.aggregator --source <dir> --mode summary_with_risk` | **全景回归聚合**：过滤噪音、聚焦高风险、集成 Allure 跳转 | 回归总结决策报告 | 🚧 规划中 |

### 5️⃣ 基础设施与回归验证

| 命令 | 说明 |
|---|---|
| `python -m unittest tests.test_artifact_split` | 产物拆分端到端回归（意图→计划→直读→缺陷） |
| `python -m unittest tests.test_appium_chain` | Appium 混合编排链路回归 |
| `python -m unittest tests.test_business_verdict` | 业务码归因 + 两层报告呈现回归 |
| `python -m unittest tests.test_report_gate` | Release Gate 三态决策 + 聚合渲染回归 |
| `powershell -ExecutionPolicy Bypass -File scripts/setup_appium_env.ps1` | Appium+ADB+Java+Python 环境一键补齐（幂等） |
| `.\stop_pipeline.ps1 -DryRun` / `.\stop_pipeline.ps1` | 查看 / 停止设计管线进程（避免误杀） |
| `python -m unittest tests.test_atomic_skills` | 三个原子 Skill + 效率基线回归 |

### 6️⃣ 原子 Skill：定向击穿高频重复劳动（配效率基线）

> 对准日常耗时 Top3 的隐性重复工作，单职责、输入输出明确、确定性无 LLM、可独立跑通。

| 命令 | 干掉的重复活 | 输入 → 输出 | 实测提效 |
|---|---|---|---|
| `python -m skills_py.element_locator <页面.xml> --keyword <词> --record` | 页面改版后手动改 XPath | XML 快照 → 定位三元组（rid/AccID/XPath，带置信度） | ~150s→<1s/定位 |
| `python -m skills_py.report_synth <result.json> --record` | 手动拼截图/整理复现步骤 | 结果JSON+证据 → 风险分级 HTML（P0/P1/P2 排序） | ~8min→<1s/份 |
| `python -m skills_py.env_guardian <serial> <pkg> --record` | 回归值守手动重启App/清弹窗 | 检测崩溃/弹窗/超时 → 自动自愈 | ~10min→~3s/次 |
| `python -m core.efficiency report --html` | — | 手工基线 vs Agent 耗时 → 提效对比报告 | output/baselines/efficiency_report.html |

- 效率基线：`config/efficiency_baseline.yaml` 存手工标准耗时（用 `python -m core.efficiency record <skill> --manual <秒>` 实测 3 次校准）
- 计时口径：`timed()` 按 items 摊销为"每单位耗时"，与基线同口径；`--record` 自动登记
- 提效比 = (1 − Agent耗时/手工基线) × 100%；≥70% 视为定向击穿

> 说明：`execution/runner.py` 是执行库类（`ExecutionRunner`），直接运行它等价于跑
> S6 批量回归；若要单独构造 ExecutionPlan 交给 runner，请 import `ExecutionRunner`/
> `plan_from_capture` 等，或用 `python -m orchestrator.run_strategy --mode regression`。

## 目录速览

- `agents/` 设计管线 5 阶段 9 个 Agent
- `workflow/qa_workflow.py` 5 阶段编排
- `schema/` JSON Schema（全流程）
- `skills/` LLM Skill Prompt（含 tc-to-plan）
- `execution/`、`tools/`、`evidence/`、`verification/` 执行域
- `docs/project_status_report.html` 项目全景说明
- `docs/execution_architecture.html` 执行入口与发动机架构说明

## 详细文档

- 项目全景：见 [docs/project_status_report.html](docs/project_status_report.html)。
- 执行入口与发动机架构（S0–S6 全景 · TC→Plan→执行(API+Appium/ADB+DB)→采证→断言→报告 链路 · 步骤类型矩阵 · 报告产物）：见 [docs/execution_architecture.html](docs/execution_architecture.html)。
- Appium + ADB + Java + Python 环境配置命令：见 [docs/appium_env_setup.md](docs/appium_env_setup.md)（一键脚本 `scripts/setup_appium_env.ps1`）。