# AI-Test-Agent 项目操作与修改说明书

本文档面向需要**自己运行**和**自己改代码**的维护者。上半部分讲怎么"操作"（有哪些入口、每条命令干什么、产物在哪），下半部分讲怎么"修改"（要动某个能力去改哪个文件），最后是常见报错与边界。

> 本文档与**状态报告**（讲述了项目价值、架构与一次真实回归的结论）互补：看"为什么"读 `docs/project_status_report.html`，看"怎么跑 / 怎么改"读本文件。

---

## 1. 环境与依赖

在跑任何东西之前，需要这几样就位：

| 依赖 | 说明 | 检查命令 |
|---|---|---|
| Python 环境 | 项目用 `.venv`，Python 3.10–3.14 均可 | `python --version` |
| 依赖包 | 从 `requirements.txt` 安装 | `pip install -r requirements.txt` |
| LLM 凭据 | 在 `.env`，走 Moonshot 兼容协议 | `python -c "import config; print(config.MODEL)"` |
| Android 设备 | S6 稳定性 / UI 层需要真机或模拟器 | `adb devices`（示例 `emulator-5554`） |
| 抓包目录 | S6 回放素材来源，默认 `D:/higo-api` | 目录内有 whistle 导出的 txt |

`.env` 唯一要改的是三个键：

```
MOONSHOT_API_KEY=...
MOONSHOT_BASE_URL=https://open.bigmodel.cn/api/paas/v4
MODEL=glm-4.5-air
```

`config.py` 只是把它们读进来（`load_dotenv`），**换模型直接改 `.env`，不用动代码**。

---

## 2. 目录结构总览

```
AI-Test-Agent/
├── main.py                     S1–S5 端到端（读 input/，跑完整 QAWorkflow）
├── run_s6_execution.py         S6 批量回归（抓包回放 + TC 批量 + ADB/UI）
├── run_redpacket_e2e.py        发红包 E2E：API + ADB/UI 联动演示
├── run_account_health.py       账号健康度巡检（登录可用性 + 样本关联）
├── run_s2_chunked.py 等        各阶段独立联调脚本（见 §3）
├── orchestrator/               S6 分层测试决策：strategy / delegate / run_strategy
├── stability/                  稳定性三层：actor / runner / monitor / recorder / attacks
├── replay/                     replay：capture_replay 抓包回放、account_health 账号巡检
├── execution/                  S6 执行引擎：planner / runner / result / batch_regression / ui_flow
├── agents/                     9 个 LLM 智能体（解析/抽取/建模/缺口/设计/生成/校验/评审/门禁）
├── workflow/                   QAWorkflow（S1–S6 编排）
├── schema/                     9 个 JSON Schema（各阶段产物校验）
├── verification/               校验器（PlanValidator 等）
├── tools/{api,android,db}/    APIClient / ADBClient / DBClient + whistle_parser
├── evidence/                   API/ADB 证据采集：collector / models / store
├── configs/skills.py           SKILLS 配置字典（LLM Agent 技能路径的唯一来源）
├── output/                     全部运行产物（见 §5）
├── docs/project_status_report.html   状态报告（项目价值与结论）
└── input/                      S1 需求文档入口（.docx/.txt/.md）
```

---

## 3. 如何操作：运行入口一览

所有命令在项目根目录执行。

### 3.1 从头跑 S1–S5（端到端）

S1–S5 是一个流水线：读需求 → 解析 → 事实抽取 → 业务建模 → 缺口 → 测试设计 → 用例生成 → 评审 → 门禁。

```powershell
# 把需求文档放进 input/ 目录（.docx/.txt/.md），然后：
python main.py
```

产物（`output/` 下）：

| 阶段 | 产物 |
|---|---|
| S1 需求理解 | `parsed.json`、`facts.json` |
| S2 需求分析 | `analysis.json`、`gaps.json` |
| S3 测试设计 | `test_design.json` |
| S4 用例生成 | `test_cases.json` |
| S5 用例评审 | `validation_result.json`、`quality_review.json`、`release_gate.json` |

`main.py` 结束时打印发布门禁结论（PASS / CONDITIONAL / BLOCK）和评审问题清单。

> 提示：S1–S5 走 LLM，一个完整跑一次通常需要**几十分钟**（S1 重跑 + S4 用例生成最耗时），适合放后台执行。

### 3.2 分阶段独立联调

只想跑某个阶段、不想每次重跑 S1 时，用对应的联调脚本（它们读取上一步产物，见文件头注释）：

| 命令 | 作用 |
|---|---|
| `python run_s2_chunked.py` | 读 `output/facts.json`，跑分块并行业务建模 → `analysis_chunked.json` |
| `python run_s3_design.py` | 测试设计 |
| `python run_s3_gap.py` | 缺口检测 |
| `python run_s4_gen.py` | 用例生成 |
| `python run_s5.py` | 用例校验 + 评审 + 门禁 |

### 3.3 S6 批量回归（核心价值所在）

对抓包目录里的接口做真实回放 + 全量 TC 批量 + ADB/UI 验证，自动采证据、自动判结论。

```powershell
python run_s6_execution.py [capture_dir] [endpoint_substring] [device_serial]
# 示例（默认值）：
python run_s6_execution.py D:/higo-api send_red_packet emulator-5554
```

产物：`output/evidence_batch_regression/`（逐用例 request/response/headers/execution 四件套）

### 3.4 发红包 E2E 演示

一键跑通"后端 API 原样回放 + 前端 ADB 找红包入口并点击验证"：

```powershell
python run_redpacket_e2e.py
```

产物：`output/evidence_higo_redpacket_e2e/`

### 3.5 账号健康度巡检

回放每个账号的登录样本判定授权可用性，并把发红包样本按 `mid` 关联到账号：

```powershell
python run_account_health.py                 # 实际回放登录
python run_account_health.py --dry-run       # 只汇总结构，不回放（无副作用）
```

产物：`output/evidence_account_health/account_health.json`

### 3.6 测试策略决策 + 三层分层执行（S6 统一入口）

这是分层测试的统一入口：先决策跑哪些层，再分派给业务/攻击/稳定各层，最后聚合成一份统一报告。

```powershell
# 决策决策（dry-run，只落盘计划不执行）
python -m orchestrator.run_strategy --mode smoke    --dry-run
python -m orchestrator.run_strategy --mode regression
python -m orchestrator.run_strategy --mode nightly

# 真机执行（可带风险等级、稳定性事件量覆盖）
python -m orchestrator.run_strategy --mode regression --risk high \
    --target 发送红包 --stability-events 40 --device emulator-5554
```

参数：`--mode smoke|regression|nightly`、`--risk low|medium|high|critical`、`--target 业务点`、`--endpoint`、`--capture-dir`、`--stability-events`、`--dry-run`。

产物：`output/plan.json`（决策计划）、`output/strategy/strategy_report.json`（统一报告，含 verdict）。

### 3.7 稳定性层单独跑

状态感知随机执行 + Crash/ANR 监控：

```powershell
python -m stability.runner --events 40 --device emulator-5554
```

参数：`--events` 事件量、`--seed`、`--strategy RANDOM|ATTACK|REPLAY`、`--anchor-bias`、`--test-id`。产物：`output/evidence_stability/execution_result.json`。

---

## 4. 三层测试架构与执行原语

S6 分层执行由三层组成，统一由 `orchestrator/` 分派：

| 层 | 干什么 | 实现 | 决策矩阵控制 |
|---|---|---|---|
| **业务层** | 对指定端点**字节级原样回放**抓包请求，断言"复现抓包业务码" | `replay/capture_replay.py` | 每端点代表 / 全量 TC |
| **攻击层** | 跑本机可执行的攻击用例（连点/重复/重放/断网/切后台/杀进程） | `stability/attacks.py` | 可执行攻击子集 |
| **稳定性层** | 状态感知随机操作 + Crash/ANR 监控，验证无崩溃/卡死 | `stability/runner.py` | 事件量 |

三种模式的决策矩阵见 `orchestrator/strategy.py` 的 `_BASE_MATRIX`：

| 模式 | 业务 | 攻击 | 稳定性事件量 |
|---|---|---|---|
| `smoke` | 每端点探针 1 条 | 关闭 | 40 |
| `regression` | 全量 TC | 可执行 6 条 | 1000 |
| `nightly` | 全量 TC | 可执行全量 | 10000 |

执行原语（`stability/actor.py` 的 `act`）：`TAP`、`SWIPE`、`KEY`、`BACKGROUND`、`BURST_TAP`。攻击层额外支持 `REPLAY`、`FOREGROUND`、`NET_OFF`/`NET_ON`、`KILL_APP`/`RELAUNCH`（在 `orchestrator/delegate.py` 实现）。

---

## 5. 产物与报告

`output/` 的约定：

- 每个阶段的汇总 JSON 在 `output/*.json`。
- 每条用例/每层执行的**证据**分目录落盘：API 四件套（`*_request/json`、`*_response/json`、`*_headers/json`、`*_execution_meta/json`），ADB 三件套（`*_command/json`、`*_output/json`、`*_execution/json`）+ 按需 `screenshot`/`logcat`，DB 三件套（`db_query/json`、`db_snapshot/json`、`db_execution/json`）。
- 统一报告入口：`output/strategy/strategy_report.json`。

三层报告的 `verdict` 判定规则：业务通过率 ≥ 门槛、稳定性崩溃数 = 0、攻击可执行用例全部通过；否则 WARN/GATED，稳定性失败则 FAIL。

### 5.1 一次 regression 闭环的真实结果示例

下面是一次 `--mode regression --risk low --stability-events 40` 真机跑出的 `output/strategy/strategy_report.json` 摘要，用来帮助理解报告长什么样。

| 层 | 状态 | n_run / n_pass | 观察 | verdict 影响 |
|---|---|---|---|---|
| **业务** | WARN | 44 / 7 | 44 条端点回放中后 7 条（抓包较新样本）复现 `ret=1` 成功；前 37 条旧样本回放得 `ret=-11`（授权过期） | 通过率 15.9% < 0.90 触发 |
| **攻击** | 待重跑 | — | 第一轮因实现 bug（调用了 `ADBClient` 不存在的 `close()`）整体 ERROR，已修复 | — |
| **稳定** | PASS | 40 / 40 | 状态感知随机 40 事件，无 crash/anr/force_close/freeze | 不触发 |

最终 `verdict = WARN/GATED`：稳定性通过所以不是 FAIL，但业务通过率未达门槛，需人工裁决。

读报告要点：
- **业务层** `detail.outcomes[].passed` 才是"复现抓包业务码"的判定；`captured.ret`（抓包原码）与 `replayed_ret`（回放实际）对比，用来归因业务状态（如 `-11` 授权过期、`-1` 防重放）。
- **攻击层** 若 `error` 非空，说明该层执行链有 bug，`detail` 为 null，先看实现而非业务。
- **稳定层** `stability_result.failures[]` 列出每个 crash/anr/freeze 的 `seq`、pattern 与 logcat 路径；为空即全绿。

---

## 6. 如何修改：常见改动都动哪个文件

这是"改代码"的地图，按你想要的改动找文件。

| 想改什么 | 改哪里 |
|---|---|
| 各模式的层开关 / 事件量 | `orchestrator/strategy.py` 的 `_BASE_MATRIX` |
| 风险等级上调幅度 | 同上，`_rationalize()` |
| 增删攻击用例 | `stability/attacks.py` 的 `build_attack_catalog()`；`feasibility` 取值 `executable / needs_sign / needs_infra` |
| 攻击用例动作序列 | 同上，`action_seq` 字段 |
| 加新的执行原语 | 先加 `stability/actor.py::act` 的 `elif kind` 分支，再在 `orchestrator/delegate.py` 的 `_run_one_attack` 里补同一分支（该文件当前已实现 `REPLAY/FOREGROUND/NET_OFF/NET_ON/KILL_APP/RELAUNCH`） |
| 稳定性随机策略（锚点词、动作概率） | `stability/actor.py`：`ANCHOR_PATS`、`LOGIN_PATS` 正则，`choose()` 的动作概率权重 |
| 稳定性事件量 / 轮询监控频率 | `stability/runner.py`：`StabilityRunner(events=, poll_every=)` |
| Crash/ANR 判定模式 | `stability/monitor.py` |
| 抓包回放的目标/策略 | `replay/capture_replay.py`：`pick_successful()`、`run()` |
| LLM 模型 / 凭据 | `.env`（`MODEL` 等），`config.py` 自动读取 |
| Agent 技能路径 | `configs/skills.py`（**不要**在别处硬编码路径） |
| 阶段产物 JSON 结构校验 | `schema/*.json`（9 个） |
| 执行计划校验 | `verification/`（`PlanValidator`：API 必来自 Capability、method/path 匹配、config 完整、断言来自 TC、无未知步骤类型） |
| S6 批量回归步长/TC 来源 | `execution/batch_regression.py` 的 `RegressionConfig`（`tc_field` 默认 `output/test_cases.json#test_cases`） |

### 6.1 举例：给 smoke 也开攻击层

```python
# orchestrator/strategy.py
_BASE_MATRIX = {
    "smoke": {
        "business": {"enabled": True, "ref": "probe1"},
        "attack":   {"enabled": False},          # ← 改为 True，并给 ref
        "stability": {"enabled": True, "events": 40},
    },
    ...
}
```

### 6.2 举例：加一条攻击用例

在 `stability/attacks.py` 的 `build_attack_catalog()` 列表中补：

```python
AttackCase("A11", "连续发送两次红包", victim,
           ["BURST_TAP:*sendelement*", "REPLAY:1"], "连续/重复", "executable",
           "连点后立刻再原样回放一次，验证幂等"),
```

只要 `feasibility == "executable"` 且动作序列走已支持的原语，`delegate.py` 会自动把它纳入回归/夜间覆盖。

---

## 7. 常见报错与已知边界

**业务码是观测不是缺陷。** 回放返回的 `ret` 是后端业务状态，要和产品缺陷分开看：

| 现象 | 含义 | 处理 |
|---|---|---|
| `ret=-1` | 后端防重放/限频拒绝（同一 sign 的请求短窗口内被拒） | 属接口边界，协议层可达即可；要验证业务成功态需冷却或换样本/token |
| `ret=-11` | 授权过期 / token 失效 | 旧抓包样本长时间后原样回放的结果，属诚实观测；用 `run_account_health.py` 刷新最新 token 的样本 |
| `ret=-101` | 频率/状态限制 | 常见于连续批量回放，属正常业务状态码 |

**sign 重放约束（重要）。** `sign` 是对 `h_ts + token + body` 的**原始字节**计算的。回放**必须**用 `req_body_raw` 原始字符串走 `data=` 发送，绝不能重排、重序列化或刷新 `h_ts`，否则 sign 失配得到 `ret=-1`。`replay/capture_replay.py` 已按此实现，改代码时不要"优化"成解析后重发。

**成功码不硬编码。** 不同接口的 `success ret` 不同（发红包是 `ret=1 + data.status=0`，用 `ret=0` 断言会误判失败）。统一用 `CapturedAPI.is_success` 启发式，断言"复现抓包时的业务码"。

**ADB UI dump 权限。** UI dump 文件写 `/sdcard`（写 `/data/local/tmp` 在某些环境不可写会拿空状态）。

**稳定性耗时。** 约 8 秒/事件，`nightly` 的 10000 事件实际不可在单机上短时完成；10 万级目标需稀疏 UI dump + 多设备并行（当前未实现）。

**fake/deterministic 判定可能误报 freeze。** `Watchdog`/渲染无关日志可能被 CrashMonitor 判为 freeze，`stability/monitor.py` 的模式匹配是启发式。

**JSON 解析。** LLM 输出若含 Markdown 环绕或裸双引号，解析器会做容错（转义内引号）。抽 Fact/建模用中文全角引号替代 ASCII 双引号，是防解析失败的手段。不用改造。

**LLM 超时。** 大输出易超时；`timeout=600 + max_retries=1` 是平衡取舍，别盲目调大。

---

## 8. 通用开发约定（改代码前先读）

这些是踩过坑后沉淀的约定，写代码/改代码时请遵守，否则容易踩雷：

1. **LLM Agent 技能路径一律走 `configs/skills.py` 的 `SKILLS` 字典**，不要在业务代码里硬编码路径。
2. **执行步骤按类型分类**（api / db / adb / manual），每类有对应的 `config` 结构；`ExecutionPlan` 必须过 `PlanValidator` 才能跑。
3. **证据按类型落盘**：API 四件套、ADB 三件套、DB 三件套，各自文件固定命名。
4. **先出业务模型再生用例**：测试设计先产测试模型（对象/状态/条件/业务流/风险点），`source_facts` 保溯源、防幻觉。
5. **需求分析 Fact > 45 条时用分块并行建模**（25 Fact/块），分块校验放宽 minItems=0，仅最终合并结果走严格校验。
6. **JSON 产物必须可被直接 `json.load`**：剔除 Markdown 环绕、转义裸双引号（用中文全角引号替代 ASCII 双引号）。
7. **ADB 输出按 `utf-8, errors="replace"` 读**，否则非 UTF-8 字节会抛 `UnicodeDecodeError` 导致证据静默丢失。
8. **增量开发**：API → DB → Android 分步做，比一次性全接更稳；API 成功不等于业务成功，要验 DB 状态与 UI 行为做端到端确认。