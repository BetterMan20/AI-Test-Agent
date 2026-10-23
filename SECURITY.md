# 安全策略

本仓库的目标是「密钥零入库」。下面把数据分级、存放位置、自动防线和泄漏处置固定下来，
所有人（包括 AI 助手）按此执行。

## 1. 数据分级

| 级别 | 内容 | 是否允许进 Git / 远程 |
|---|---|---|
| L0 公开 | 公开服务端点（如 `open.bigmodel.cn`）、开源依赖、文档 | ✅ 允许 |
| L1 内部 | 测试环境域名、设备 serial、项目代号 | ✅ 允许（生产环境一律 ❌） |
| L2 密钥 | 密码、API Key、token、`zyp`、`sign`、私钥、带口令的连接串 | ❌ 严禁 |
| L3 个人数据 | 真实手机号、账号库、登录样本、用户数据导出 | ❌ 严禁 |

判断标准：**一段内容泄漏后是否需要「换掉」而不是「删掉」？** 需要换掉的都是 L2。

## 2. 存放位置

| 内容 | 位置 |
|---|---|
| L2 / L3 | `.env`（已 gitignore）或 `secrets/`（已 gitignore） |
| L1 测试环境地址 | `config/environments/<proj>-<env>.yaml` |
| 模板与说明 | `.env.example`（只有占位符，无真实值） |

`core/config/loader.py` 是唯一注入点：它从 `.env` 读取 `HIGO_ZYP`、`HIGO_X_XC_AGENT`
等并合并进请求头，业务代码不接触明文。

## 3. 三层自动防线

| 层 | 触发时机 | 覆盖范围 | 启用方式 |
|---|---|---|---|
| pre-commit | `git commit` | 暂存区文件（含 zip 内部文本） | `scripts/install_hooks.ps1` |
| pre-push | `git push` | 工作区 + 全历史 + `.env` 值反查 | 同上 |
| GitHub Actions | 每次 push / PR | 全历史（含已删除文件） | 已提交 `.github/workflows/secret-scan.yml` |

钩子不在仓库里自动生效（Git 的安全设计），**克隆后请执行一次**：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install_hooks.ps1
```

手动自检：

```powershell
.venv\Scripts\python.exe scripts\secret_scan.py
```

扫描器只打印「规则名 + 文件/提交位置」，不回显命中内容，避免二次泄漏。

## 4. 本次审计结论（2026-10-23）

- 扫描范围：15 个提交的全部历史 + 工作区 209 个跟踪文件 + 历史中的报告 zip。
- **真实密钥：0 命中**。`.env` 中 Moonshot Key、HIGO 身份头、RDS/Redis/Mongo 口令
  均未出现在任何历史文件里。
- **数据库主机：0 命中**。仓库内没有生产或测试数据库地址。
- 唯一命中为 `MOONSHOT_BASE_URL`（`https://open.bigmodel.cn/api/paas/v4`），属 L0
  公开端点，已加入反查白名单。
- 仓库中公开的 L1 地址仅：`api-chat-test.youyisia.com`、`test-api.miregame.com`、
  `127.0.0.1`（Appium 本机）、`open.bigmodel.cn`。

## 5. 万一发生泄漏（顺序不能颠倒）

1. **先轮换**：立即在对应平台作废/重置该凭据。清理历史需要时间，窗口期靠轮换兜底。
2. **再移除**：从当前工作区删除，提交修复。
3. **清历史**：用 `git filter-repo` 重写（示例，执行前先备份裸仓库）：

   ```bash
   git filter-repo --invert-paths --path secrets/ --path .env --force
   git push --force --all
   ```

4. **通知**：所有协作者重新克隆——旧克隆里仍留着密钥。
5. **复盘**：查该凭据的使用记录，确认没有异常调用。

## 6. GitHub 侧需手工开启（本地命令无法代替）

仓库 → **Settings → Code security and analysis**：

- **Secret scanning**：开启（公开仓库免费）
- **Push protection**：开启，阻止带密钥的 push
- **Dependabot alerts**：开启

## 7. 报告问题

发现疑似泄漏请**私下**联系维护者（`BetterMan20`），不要开公开 issue，也不要在
issue 里贴出密钥片段。

## 8. 已知边界

- 扫描器基于正则，能覆盖常见密钥形态，但不能证明「绝对没有」。真正兜底的是
  GitHub Push Protection 与凭据轮换机制。
- `.env` 是明文文件，本机被入侵时等同泄漏；高价值凭据建议改用系统密钥库
  或 CI Secret。
- `tools/appium/.appium/` 中的依赖锁文件属于构建产物，不含密钥，但会增大仓库体积。
