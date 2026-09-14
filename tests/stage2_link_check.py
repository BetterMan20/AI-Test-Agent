# 针对“链接开头 ≠ 无业务”修复的定向验证。
# 构造一个“埋点/figma 链接开头 + 大量业务规则在后”的需求段落，
# 走 FactExtraction，确认它提取业务 Fact 而不是整节跳过。

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.fact_extraction import FactExtraction


MOCK = """## 四、需求详情
埋点：
请至钉钉文档查看附件《【房间】红包优化 数据需求》。
figma：
https://www.figma.com/design/sample
多语言：
https://docs.google.com/spreadsheets/d/sample

普通红包展示：
发送金币栏（4个档位）：399、999、3,999、9,999
发送人数栏（4个档位）：x5、x15、x25、x40
倒计时栏：立即、2mins、5mins
余额不足时，toast提示"余额不足"，1s后自动跳转至充值页。
"""


def main():
    ext = FactExtraction()
    result = ext.run(MOCK)
    facts = result.get("facts", [])
    print(f"N_FACTS={len(facts)}")

    contents = [f"{f['type']}: {f['content']}" for f in facts]
    for c in contents:
        print("  -", c)

    topics = " ".join(contents)
    key = ["399", "999", "x5", "2mins", "余额不足", "跳转至充值页"]
    missing = [k for k in key if k not in topics]
    if missing:
        print(f"\n[FAIL] 以下关键业务点未提取: {missing}")
        raise SystemExit(1)

    # 链接本身不应被当作业务 Fact
    linky = [c for c in contents if any(
        s in c for s in ["figma", "docs.google", "https", "请至钉钉"]
    )]
    if linky:
        print(f"\n[WARN] 链接/元数据被提取为业务Fact: {linky}")

    print("\n[PASS] 模型不再因链接跳过业务内容")
    Path("output/stage2_link_check.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()