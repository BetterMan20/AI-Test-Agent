# 架构说明

本文说明 AI-Test-Agent 的分层、数据流与扩展点，面向需要改代码或接新项目的人。
「怎么跑」见 [OPERATION_GUIDE.md](OPERATION_GUIDE.md)，「为什么这么设计」见
[project_status_report.html](project_status_report.html)。

---

## 1. 两条主线

| 主线 | 阶段 | 驱动方式 | 入口 |
|---|---|---|---|
| 设计管线 | S1–S5：需求 → 测试设计 → 用例 → 评审门禁 | LLM + 确定性校验 | `python main.py` |
| 执行与决策 | S6–S7：计划 → 执行 → 采证 → 断言 → 报告门禁 | 确定性（无 LLM） | `python -m execution.planner` / `python execution/runner.py` / `python -m execution.report` |

设计管线保证「测什么」可追溯，执行管线保证「测得怎么样」有证据、可复核。两者用
`ExecutionPlan`（执行层契约）解耦：设计产物可以先入库，执行侧再独立消费。

## 2. 目录职责

```
agents/        9 个 LLM Agent（S1 解析/抽取，S2 建模/缺口，S3 设计，S4 生成，S5 校验/评审/门禁）
workflow/      QAWorkflow：S1–S6 编排 + 用例意图回填（case_intent.py）
schema/        10 个 JSON Schema，逐阶段产物契约
skills/        LLM Skill Prompt（.skill.md），由 configs/skills.py 登记
configs/       SKILLS 字典：技能名 → Prompt 路径的唯一来源
engine.py      TestEngine：三个入口汇聚到一个执行引擎
execution/     planner（TC/抓包→Plan）、runner（执行步骤）、report（聚合+门禁）、business_verdict、defect_draft
evidence/      EvidenceCollector / EvidenceStore：证据落盘与索引
verification/  PlanValidator（计划合法性）、RuleVerifier（6 种断言）
tools/         api / db / android / appium 四类客户端 + whistle 抓包解析
orchestrator/  分层测试决策：strategy / delegate / run_strategy
projects/      项目适配器（higo、a）：业务动作、状态读取、证据采集
core/          项目无关内核：adapters 注册表、config 加载、qa 探索循环、attack、discovery、efficiency
stability/     稳定性三层：actor / monitor / recorder / attacks
replay/        抓包回放与账号健康巡检
skills_py/     确定性原子技能（element_locator / report_synth / env_guardian）
tests/         单元与链路回归（13 个模块，151 个用例）
```

## 3. 设计管线（S1–S5）

```
requirement (input/*.docx)
  → S1 parsed.json → facts.json           RequirementParser + FactExtraction（分块并行，防截断）
  → S2 analysis.json → gaps.json          RequirementAnalysis + GapDetection
  → S3 test_design.json                   TestDesign（模型/场景/测试点/风险/覆盖）
  → S4 test_cases.json                    TestCaseGenerator（场景式链路用例）
  → S5 validation_result.json             TestCaseValidator（LLM）
       quality_review.json                QualityReview（确定性规则）
       release_gate.json                  ReleaseGate（确定性三态：PASS / CONDITIONAL / BLOCK）
```

S4 结束后由 `workflow/case_intent.py` 把「用例意图」回填进 `test_design.json`，
使其成为意图层的单一可信源；`test_cases.json` 因此降级为 S4→S5 的中间评审输入。

每个 Agent 的调用都经 `utils/skill_engine.py`：加载 `.skill.md` → 调 LLM → 按
`schema/*.json` 校验 → 失败重试/降级。Schema 校验失败是「产物不可信」的信号，
不会静默通过。

## 4. 执行管线（S6）

`TestEngine` 提供三个入口，最终都落到 `ExecutionRunner.run_plan()`：

| 入口 | 方法 | 说明 |
|---|---|---|
| A 文档用例 | `run_test_case(tc)` | `plan_from_test_case` 派生计划，可先过 PlanValidator |
| B 抓包回放 | `run_capture` / `run_captures_from_dir` | `plan_from_capture` 直接回放真实请求 |
| C 手写计划 | `run_plan(plan)` / `run_plans(plans)` | 跳过派生，直接执行 |

计划的步骤类型共 5 类：`manual` / `api` / `db` / `adb` / `appium`；Appium 按 operation
懒启动会话分派。每步执行后采集证据（request/response/headers、db_snapshot、
adb_output、appium_page_source、screenshot、logcat），再用 6 种断言校验：
`status_code`、`json_path`、`text_contains`、`regex`、`count`、`db_rows`。

失败落 `output/defects/<tc_id>.{json,md}` 草稿：`fail` 归为疑似产品缺陷，
`error` 归为疑似环境问题，交人工确认后再提单。

## 5. 报告与门禁（S7）

`execution/report.py` 聚合原始 JSON、截图与缺陷草稿，产出人读 HTML +
机读 `release_gate.json` + 人工核查清单。门禁三态与 S5 的三态**不是同一套**：

| 来源 | 取值 | 含义 |
|---|---|---|
| S5 `agents/release_gate.py` | `PASS` / `CONDITIONAL` / `BLOCK` | 用例质量门禁 |
| S7 `execution/report.py` | `GO` / `GO_WITH_WARNINGS` / `NO_GO` | 发布决策门禁 |

S7 的判定顺序：协议层有 fail/error 或存在未决缺陷 → `NO_GO`；协议全过但业务未复现
（仅环境归因）→ `GO_WITH_WARNINGS`；全部复现 → `GO`。`execution/business_verdict.py`
负责业务码的确定性归因（复现 / 凭证失效 / 防重放 / 限频 / 业务不符），避免把环境问题
误判成产品缺陷。

## 6. 探索与专项能力（S0 附加）

- `core/qa/cycle.py`：七阶段探索循环（认识 → 建模 → 找风险 → 攻击 → 验证 → 回归 → 学习），
  产物落 `knowledge/` 与 `output/qa/`。
- `core/discovery/`：App KB 与页面探索；`core/attack/`：一致性攻击引擎与 LLM 决策。
- `stability/`：状态感知随机操作 + Crash/ANR 监控；`replay/`：抓包回放、账号健康巡检。
- `orchestrator/`：把业务 / 攻击 / 稳定性三层解耦成可独立回归的策略。
- `core/efficiency.py` + `skills_py/`：原子技能与效率基线（手工耗时 vs Agent 耗时）。

## 7. 项目适配契约

Core 层不认识具体业务。新增一个项目只需要：

1. `config/projects/<proj>.yaml` 声明 `capabilities`、`adapter.module`、`adapter.actions`；
2. `config/environments/<proj>-<env>.yaml` 填 API 地址、设备 serial、头部模板（不放密钥）；
3. `projects/<proj>/adapters/` 实现 `execute_action` / `get_state` / `collect_evidence`。

适配器由 `core/adapters/registry.py` 按配置动态加载，统一返回 `ActionResult`。
`projects/a/adapters/mic_fill.py` 是典型例子：它把「登录 / 进房 / 麦位」回调注入
`core/load.py` 的通用并发加载引擎，Core 侧只做并发、补位与证据落盘。

## 8. 配置与密钥分层

```
config/global.yaml                     跨项目默认（证据目录、超时、菜单任务）
config/projects/<proj>.yaml            项目能力与适配器声明
config/environments/<proj>-<env>.yaml  环境地址、设备、非敏感头部模板
.env                                   密钥（LLM Key、zyp、DB/Redis 口令）—— 已 gitignore
secrets/                               登录样本/账号库等敏感文件 —— 已 gitignore
```

优先级：环境层 > 项目层 > 全局层；`core/config/loader.py` 负责合并并把 `.env` 中的
敏感项注入。任何密钥都不应写进 yaml 或代码。

## 9. 扩展点

| 要做什么 | 改哪里 |
|---|---|
| 新增项目 | 见 §7，三处配置 + 一个 adapters 目录 |
| 新增步骤类型 | `execution/runner.py::_run_step` 分派 + `schema/execution_plan.schema.json` + 证据类型枚举 |
| 新增断言 | `verification/rule_verifier.py` + Plan Schema 的 assertion 枚举 |
| 新增设计阶段 | `agents/` 新增 Agent + `workflow/qa_workflow.py` 串联 + `schema/` 契约 + `skills/*.skill.md` |
| 新增确定性技能 | `skills_py/` + `config/efficiency_baseline.yaml` 基线 + `tests/test_atomic_skills.py` |

## 10. 运行前置

- **必须用 `.venv` 里的解释器**（`.venv\Scripts\python.exe`）。系统全局 Python 未装
  `jsonschema` 等依赖，直接 `import engine` 会失败。
- `input/` 只放需求文档（`.docx/.txt/.md`），`FileReader.find_input()` 取排序后的第一个；
  调试截图、UI dump、临时脚本请放 `scratch/`（已 gitignore）。
- 所有运行产物落 `output/`（已 gitignore），不要提交。
