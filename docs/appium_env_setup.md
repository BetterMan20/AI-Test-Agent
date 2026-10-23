# Appium + ADB + Java + Python 环境配置

打通「API + Appium/ADB + DB」混合编排的前提：收发 UI 业务操作的 **Appium** 跑得起来。
本文给出从零安装到验证的完整命令，并记录当前项目本体状态（`2026-09-17` 盘点）。

---

## 0. 一键脚本

已配好幂等脚本，缺啥补啥：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_appium_env.ps1
```

输出末尾会校验六件套：Python / Node / Java / ADB / Appium-Python-Client / uiautomator2 驱动。

---

## 1. 当前项目本体状态（2026-09-17 实测）

| 组件 | 版本/状态 | 承载位置 |
|---|---|---|
| Python | 3.10.11 | 系统 PATH |
| Node.js | v22.16.0 | 系统 PATH |
| Java | OpenJDK 21.0.10 LTS | 系统 PATH |
| ADB | 1.0.32 · ANDROID_HOME=`D:\SDK` | platform-tools |
| Appium Server | appium ^3.7（node） | `tools/appium/node_modules`（项目内） |
| UiAutomator2 驱动 | appium-uiautomator2-driver 8.7.0 | `tools/appium/.appium`（`APPIUM_HOME` 指向此处） |
| **Appium Python 客户端** | **未安装** | 缺 → 见 §2 |

> 结论：Appium 服务端/驱动、Node、Java、ADB 均已就绪，**当前唯一缺失的是 Python 侧的
> `Appium-Python-Client`**。装上即可（`tools/appium/higo_ui.py` 顶部 `from appium import webdriver` 需要它）。

---

## 2. Python 侧（本项目直接依赖）

```powershell
# 本项目的执行引擎依赖 Appium Python 客户端
python -m pip install --upgrade pip
python -m pip install "Appium-Python-Client>=3.0"

# 验证
python -c "import appium; print('Appium-Python-Client', appium.__version__)"
```

运行/开发本引擎的其他依赖，若未装则一并补齐（fastapi/requests/pyyaml/pymysql 等按 `requirements` 安装）。

---

## 3. Node + Appium Server（项目内，免全局安装）

本项目把 Appium server 与驱动都收进 `tools/appium/`，跑的时候设 `APPIUM_HOME` 指到 `tools/appium/.appium`，无需污染全局。

```powershell
# 二选一：
# 方式A（推荐）：用项目一键脚本
powershell -ExecutionPolicy Bypass -File scripts/setup_appium_env.ps1

# 方式B（手动）：
cd tools\appium
npm install                                     # 装 appium ^3.7 到 node_modules
$env:APPIUM_HOME = "<项目根>\tools\appium\.appium"
node node_modules\appium\build\lib\main.js driver install uiautomator2   # 装驱动
```

手动验证 server 可启动：

```powershell
$env:APPIUM_HOME = "<项目根>\tools\appium\.appium"
node "<项目根>\tools\appium\node_modules\appium\build\lib\main.js" --version
node "<项目根>\tools\appium\node_modules\appium\build\lib\main.js" driver list --installed
# 期望看到 appium-uiautomator2-driver@8.7.0 already installed
```

> 失败常见原因：代理/npm registry 拉不到包 → `npm config set registry https://registry.npmmirror.com` 后重试。

---

## 4. Node 环境（若全新机器）

```powershell
# Windows 手动：到 https://nodejs.org 下载 LTS 安装包，安装时要勾选 “Add to PATH”
# 或在 PowerShell 用 winget：
winget install OpenJS.NodeJS.LTS

# 验证
node -v
```

---

## 5. Java（UiAutomator2 工具链可选；一般已随系统安装）

```powershell
# 验证
java -version        # 期望 openjdk 21 或更高
echo "JAVA_HOME=$env:JAVA_HOME"   # 建议指向 JDK 根

# winget 若缺：
winget install EclipseAdoptium.Temurin.21.JDK
```

> Appium 的 UiAutomator2 驱动主要靠 adb 部署 `appium-uiautomator2-server`，不强依赖 Java；
> 但若将来接 Espresso / 需要 UIAutomator 本地编译则必须。装上无害。

---

## 6. ADB（Android SDK platform-tools）

```powershell
# 建议系统变量
ANDROID_HOME = D:\SDK
# 把 %ANDROID_HOME%\platform-tools; %ANDROID_HOME%\platform-tools\bin 加入 PATH

# 手动装（Android Studio 或命令行）：
winget install Google.AndroidStudio    # 若愿意装整套 IDE
# 或用 sdkmanager（命令行，Android cmdline-tools）：
sdkmanager "platform-tools" "platforms;android-34" "build-tools;34.0.0"

# 验证 + 看设备
adb version
adb devices          # 期望一台 emulator-5554 或真机 serial
```

> 本项目 `tools/android/client.py`（设备控制/截图/logcat）直接调 `adb`，所以 adb 必须在 PATH。

---

## 7. 端到端联通验证

```powershell
python -c "import appium, appium.webdriver, appium.options.android, appium.webdriver.common.appiumby; print('Appium-py import OK')"

# 若想真机跑 appium 步骤，把计划(含 appium 步骤)交给 engine：
python -c "from engine import TestEngine; e=TestEngine(adb_device_serial='emulator-5554', evidence_dir='output/evidence'); print(type(e._appium_client).__name__, '<- appium client 已装配'); e.close()"
# 期望打印 AppiumController 且不报 import 错误
```

---

## 8. appium 步骤怎么写（引擎接线的 schema）

执行引擎已把 `appium` 接入第 5 种步骤类型，`ExecutionPlan.steps[].*` 的 `appium` 节配置：

| 字段 | 说明 | 示例 |
|---|---|---|
| `operation` | 必填：UI 操作 | `tap` `input_text` `swipe` `back` `find` `page_source` `session_start` `session_close` |
| `target` | resource-id（自动补 `包名:id/` 前缀） | `tv_red_packet_status_overlay` |
| `text` | `input_text` / `find_text` 的输入/关键词 | `"100"` |
| `desc` | `find_desc` 的 content-desc | `"发送红包"` |
| `swipe` | `[x1,y1,x2,y2,dur_ms]` | `[0,800,0,200,300]` |
| `timeout` | 默认 10s | `10` |

链路上的行为：
- `planner` —— 接受/归一化 `appium` 类型（`plan_from_test_case`/`plan_from_dict`/`plan_from_capture`）。
- `plan_validator` —— `VALID_STEP_TYPES` 已含 `appium`，并校验 `operation`/`target` 是否合法完整。
- `runner.ExecutionRunner` —— 首次遇 UI 操作**懒启动** Appium server + session，按 `operation` 分派到 `AppiumController`，**操作后回吐 page_source** 供 `text_contains` 断言，并采集 `appium_action.json / appium_page_source.xml / appium_execution.json` 三件套（另可按需 screenshot/logcat）。
- `engine.TestEngine` —— 通过 `appium_device_serial`（缺省复用 `adb_device_serial`）装配 `AppiumController`，`close()` 释放会话。

**混合编排示意**（API 预热 → Appium 开面板 → DB 校验）：

```json
{ "steps": [
  {"type": "appium", "operation": "tap",   "target": "tv_red_packet_status_overlay"},
  {"type": "appium", "operation": "input_text", "target": "et_gold", "text": "100"},
  {"type": "db",     "phase": "verify", "query": "SELECT 1"}
]}
```

---

## 9. 回归验证（确保接线未破坏既有链路）

```powershell
python -m unittest tests.test_appium_chain tests.test_tc_to_plan -v
# 期望 2 条 appium 链 + 既有 TC→Plan 用例全 OK
```