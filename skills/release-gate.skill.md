# Release Gate

## Role

Release Gate 是 QA Workflow 的最终执行准入规则。

它负责：

> 根据 Quality Validation 结果，判断当前测试资产是否允许进入测试执行。

---

# Core Principle

> Deterministic Decision + P0 First

Release Gate 不负责：

- 需求分析
- 需求补充
- 测试设计
- 测试用例生成
- 质量问题发现

只负责：

> 最终执行准入判断。

---

# Gate

只有三个结果：

```text
PASS
CONDITIONAL
BLOCK