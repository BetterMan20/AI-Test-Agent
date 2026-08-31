import json

from configs.skills import SKILLS
from utils.skill_engine import SkillEngine


class TestDesign:

    MODULES = [
        {
            "letter": "A",
            "name": "A. SVIP体验卡下发渠道",
            "min_designs": 8,
            "scenarios": [
                "活动模板下发SVIP体验卡（任务数据源/榜单数据源/抽奖池）",
                "OP后台手动下发SVIP体验卡（ka-offer）",
                "奖励包下发SVIP体验卡",
                "钓鱼奖池获得SVIP体验卡",
                "火箭玩法奖池获得SVIP体验卡",
                "游戏附加玩法奖池获得SVIP体验卡",
                "游戏签到获得SVIP体验卡",
                "游戏VIP抽奖获得SVIP体验卡",
            ],
            "test_methods": ["normal_flow", "source_condition"],
        },
        {
            "letter": "B",
            "name": "B. OP后台SVIP等级展示",
            "min_designs": 4,
            "scenarios": [
                "展示普通用户SVIP等级（无SVIP身份用户不应错误显示体验SVIP等级）",
                "展示正常SVIP用户等级",
                "体验卡生效后后台等级同步（SVIP1开启SVIP3体验卡后后台展示SVIP3）",
                "体验卡到期后后台等级恢复（恢复到实际有效SVIP等级）",
            ],
            "test_methods": ["normal_flow", "state_transition"],
        },
        {
            "letter": "C",
            "name": "C. OP手动增加SVIP身份",
            "min_designs": 9,
            "scenarios": [
                "正常增加SVIP身份（选择等级+有效期+提交，立即生效）",
                "选择最低SVIP等级",
                "选择最高SVIP等级",
                "选择不存在的SVIP等级（接口拒绝）",
                "SVIP等级为空（禁止提交）",
                "有效期为空（禁止提交）",
                "重复给同一用户增加SVIP身份",
                "下发后立即检查SVIP身份",
                "下月根据成长值正常升降级",
            ],
            "test_methods": ["normal_flow", "boundary_value", "error_guessing"],
        },
        {
            "letter": "D",
            "name": "D. 体验卡有效期",
            "min_designs": 5,
            "scenarios": [
                "下发后立即开始卡片有效期倒计时",
                "有效期到期前1秒（卡片仍有效）",
                "有效期到期瞬间（卡片失效并消失）",
                "有效期超过后（卡片不可继续使用）",
                "无有效期存量卡设置兜底时长",
            ],
            "test_methods": ["time_boundary", "boundary_value"],
        },
        {
            "letter": "E",
            "name": "E. 体验时长",
            "min_designs": 5,
            "scenarios": [
                "未开启体验卡不消耗体验时长",
                "开启体验卡后开始计算体验时长",
                "体验时长到期（卡片失效，SVIP体验身份失效）",
                "体验时长未到但卡片有效期先到（卡片因有效期先到而失效）",
                "卡片有效期未到但体验时长先到（体验时长结束后卡片失效）",
            ],
            "test_methods": ["time_boundary", "state_transition"],
        },
        {
            "letter": "F",
            "name": "F. 转赠",
            "min_designs": 5,
            "scenarios": [
                "可转赠未开启体验卡（展示转赠按钮）",
                "不可转赠体验卡（不展示转赠按钮）",
                "已开启体验卡转赠（不可转赠）",
                "钓鱼奖池SVIP卡转赠（支持转赠）",
                "已过期卡片转赠（不可转赠）",
            ],
            "test_methods": ["normal_flow", "condition_combination"],
        },
        {
            "letter": "G",
            "name": "G. 卡片展示",
            "min_designs": 3,
            "scenarios": [
                "多张相同SVIP体验卡独立展示（不合并）",
                "多张卡独立倒计时（一张到期不影响另一张）",
                "卡片名称正确（xxx1h-SVIPxxx2体验格式）",
            ],
            "test_methods": ["normal_flow", "data_combination"],
        },
        {
            "letter": "H",
            "name": "H. 体验卡开启",
            "min_designs": 3,
            "scenarios": [
                "正常开启体验卡（二次确认弹窗，确认后生效）",
                "取消开启体验卡（弹窗关闭，不生效，不扣减时长）",
                "校验开启确认弹窗文案（等级/时长/有效期正确显示）",
            ],
            "test_methods": ["normal_flow", "scenario"],
        },
        {
            "letter": "I",
            "name": "I. 体验卡切换",
            "min_designs": 5,
            "scenarios": [
                "生效中卡片切换到另一张卡（A暂停B自动开启）",
                "取消切换体验卡（原卡继续生效）",
                "切换后老卡剩余时间保留",
                "切换后重新开启老卡（从剩余时长继续计时）",
                "切换到已过期卡片（不允许切换）",
            ],
            "test_methods": ["state_transition", "normal_flow"],
        },
        {
            "letter": "J",
            "name": "J. IM触达",
            "min_designs": 7,
            "scenarios": [
                "SVIP体验卡下发触发获取IM",
                "距离过期48小时触发临期IM",
                "距离过期超过48小时不触发临期IM",
                "距离过期不足48小时触发临期IM",
                "卡片过期触发过期IM",
                "同一张卡临期IM不能重复发送",
                "多张卡分别触发IM（独立生命周期）",
            ],
            "test_methods": ["time_boundary", "normal_flow", "error_guessing"],
        },
        {
            "letter": "K",
            "name": "K. SVIP抢先体验白名单",
            "min_designs": 6,
            "scenarios": [
                "白名单用户进入新等级页面（可见新SVIP等级及新功能）",
                "白名单用户OP下发新等级体验（体验卡正常生效）",
                "未加入白名单用户查看SVIP页面（不可见新等级）",
                "未加入白名单用户OP下发新等级（体验无法生效）",
                "白名单用户只进不出（删除配置后仍保持资格）",
                "白名单用户新等级体验到期（体验失效但仍可见，可充值解锁）",
            ],
            "test_methods": ["normal_flow", "cause_effect", "error_guessing"],
        },
        {
            "letter": "L",
            "name": "L. 时间边界测试",
            "min_designs": 15,
            "scenarios": [
                "有效期设为0天",
                "有效期设为1天",
                "有效期设为最大天数",
                "有效期设为最大值+1",
                "有效期设为负数",
                "有效期设为小数",
                "体验时长设为0小时",
                "体验时长设为1小时",
                "体验时长设为最大值",
                "体验时长设为最大值+1",
                "体验时长设为负数",
                "体验时长设为小数",
                "临期48小时+1秒不触发临期IM",
                "临期刚好48小时触发临期IM",
                "临期48小时-1秒触发临期IM",
            ],
            "test_methods": ["boundary_value", "time_boundary"],
        },
        {
            "letter": "M",
            "name": "M. 卡片生命周期边界",
            "min_designs": 4,
            "scenarios": [
                "卡片有效期 > 体验时长",
                "卡片有效期 = 体验时长（两时间同时到期）",
                "卡片有效期 < 体验时长",
                "两个时间同时到期时卡片最终状态确认",
            ],
            "test_methods": ["boundary_value", "state_transition"],
        },
        {
            "letter": "N",
            "name": "N. 错误分析法-异常场景",
            "min_designs": 11,
            "scenarios": [
                "连续点击2次提交",
                "连续点击10次提交",
                "网络慢时连续提交",
                "下发过程中断网",
                "下发成功但响应超时",
                "客户端超时后再次提交",
                "两个设备同时开启同一张卡",
                "并发切换SVIP2→SVIP3和SVIP2→SVIP5",
                "到期瞬间点击开启",
                "到期瞬间点击切换",
                "到期瞬间点击转赠",
            ],
            "test_methods": ["error_guessing", "concurrency"],
        },
        {
            "letter": "O",
            "name": "O. 状态迁移测试",
            "min_designs": 8,
            "scenarios": [
                "未开启 → 使用中",
                "未开启 → 已过期",
                "使用中 → 暂停",
                "暂停 → 使用中",
                "使用中 → 已过期",
                "暂停 → 已过期",
                "未开启 → 转赠",
                "使用中 → 不允许转赠",
            ],
            "test_methods": ["state_transition"],
        },
    ]

    def run(self, analysis):

        print("========== Test Design ==========")

        normalized_analysis = self._normalize_analysis(
            analysis
        )

        all_designs = []
        all_blocked = []

        for module in self.MODULES:

            letter = module["letter"]
            name = module["name"]

            print(
                f"\n--- Module {letter}: {name} ---"
            )

            try:

                designs, blocked = (
                    self._run_module_batch(
                        normalized_analysis,
                        module
                    )
                )

                all_designs.extend(designs)

                if blocked:
                    all_blocked.extend(blocked)

                print(
                    f"  Generated {len(designs)} designs"
                )

            except Exception as e:

                print(
                    f"  Module {letter} failed: {e}"
                )

        self._renumber_designs(all_designs)

        result = self._merge_module_results(
            all_designs, all_blocked
        )

        print(
            f"\nTest Design 完成，"
            f"共 {len(all_designs)} 个设计"
        )

        return result

    # ======================================================
    # Run Module Batch
    # ======================================================

    @staticmethod
    def _run_module_batch(analysis, module):

        enhanced_input = (
            TestDesign._build_module_input(
                analysis, module
            )
        )

        print(
            "  增强输入长度：",
            len(
                json.dumps(
                    enhanced_input,
                    ensure_ascii=False
                )
            )
        )

        result = SkillEngine.run(
            skill_path=SKILLS["design"],
            user_input=enhanced_input,
            schema_path="schema/test_design.schema.json",
            output_mode="json"
        )

        designs = []
        blocked = []

        for m in result.get("modules", []):
            if isinstance(m, dict):
                tds = m.get("test_designs", [])
                if isinstance(tds, list):
                    designs.extend(tds)

        blocked = result.get("blocked_designs", [])

        for d in designs:
            if isinstance(d, dict):
                obj = d.get("test_object", "")
                if obj and not obj.startswith(module["letter"]):
                    d["test_object"] = (
                        f"{module['letter']} - {obj}"
                    )

        return designs, blocked

    # ======================================================
    # Build Module Input
    # ======================================================

    @staticmethod
    def _build_module_input(analysis, module):

        scenarios_text = "\n".join(
            f"  {i+1}. {s}"
            for i, s in enumerate(
                module["scenarios"]
            )
        )

        rules_text = TestDesign._extract_relevant_rules(
            analysis, module["letter"]
        )

        methods_text = ", ".join(
            module["test_methods"]
        )

        enhanced = {
            "instruction": (
                f"你正在为「{module['name']}」模块"
                f"生成 Test Design。\n\n"
                f"必须覆盖以下 {len(module['scenarios'])} 个测试场景，"
                f"每个场景至少1个Test Design：\n"
                f"{scenarios_text}\n\n"
                f"相关业务规则：\n{rules_text}\n\n"
                f"测试方法必须使用以下值：{methods_text}\n"
                f"test_object 必须以 \"{module['letter']} - \" 开头。\n"
                f"risk_level: P0 或 P1。\n\n"
                "每个 Test Design 必须包含所有 required 字段：\n"
                "design_id, status(READY), test_object, test_goal, "
                "requirement_refs(至少1条), risk_level, test_methods, "
                "conditions, data_dimensions, time_dimensions, "
                "state_dimensions, source_dimensions, scenario, "
                "expected_behavior(至少1条), coverage_targets(至少1条)\n\n"
                "只输出合法 JSON。"
                "JSON 必须以 { 开头，以 } 结尾。"
                "不输出 Markdown、解释、分析过程。"
            ),
            "min_test_designs": module["min_designs"],
            "module_letter": module["letter"],
            "module_name": module["name"],
            "scenarios": module["scenarios"],
            "requirement_analysis": analysis
        }

        return enhanced

    # ======================================================
    # Extract Relevant Rules
    # ======================================================

    @staticmethod
    def _extract_relevant_rules(analysis, letter):

        if not isinstance(analysis, dict):
            return "无相关规则"

        modules = analysis.get("modules", [])
        if not modules:
            return "无相关规则"

        mod = modules[0] if isinstance(modules[0], dict) else {}
        rules = []

        if letter == "A":
            for sr in mod.get("source_rules", []):
                if isinstance(sr, dict):
                    rules.append(
                        f"来源: {sr.get('source', '')}"
                        f" - {sr.get('rule', '')}"
                    )
                else:
                    rules.append(str(sr))
            rules.append("所有卡片下发后不自动生效")
            rules.append("下发卡片时同时触发一条IM")

        elif letter == "B":
            rules.append("OP后台支持展示用户SVIP等级")
            rules.append("体验卡生效后后台等级同步")
            rules.append("体验卡到期后后台等级恢复")

        elif letter == "C":
            rules.append("对单个用户进行增加SVIP身份操作")
            rules.append("选择SVIP身份等级")
            rules.append("选择下发有效期")
            rules.append("点击提交，立即生效")
            rules.append(
                "下月SVIP等级逻辑正常按上个月"
                "累积的成长值进行升降级判断"
            )

        elif letter == "D":
            for tr in mod.get("time_rules", []):
                if "有效期" in str(tr) or "倒计时" in str(tr):
                    rules.append(str(tr))
            for c in mod.get("constraints", []):
                if "有效期" in str(c) or "兜底" in str(c):
                    rules.append(str(c))
            rules.append("卡片有效期到期后卡片失效")

        elif letter == "E":
            for br in mod.get("business_rules", []):
                if "体验时长" in str(br):
                    rules.append(str(br))
            for tr in mod.get("time_rules", []):
                if "体验时长" in str(tr) or "开启" in str(tr):
                    rules.append(str(tr))

        elif letter == "F":
            for br in mod.get("business_rules", []):
                if "转赠" in str(br):
                    rules.append(str(br))

        elif letter == "G":
            for c in mod.get("constraints", []):
                if "独立" in str(c) or "名称" in str(c) or "存放" in str(c):
                    rules.append(str(c))

        elif letter == "H":
            for br in mod.get("business_rules", []):
                if "开启" in str(br) or "确认" in str(br) or "弹窗" in str(br):
                    rules.append(str(br))

        elif letter == "I":
            for br in mod.get("business_rules", []):
                if "切换" in str(br) or "暂停" in str(br):
                    rules.append(str(br))

        elif letter == "J":
            for br in mod.get("business_rules", []):
                if "im" in str(br).lower() or "触达" in str(br):
                    rules.append(str(br))
            for tr in mod.get("time_rules", []):
                if "临期" in str(tr) or "到期" in str(tr) or "48" in str(tr):
                    rules.append(str(tr))

        elif letter == "K":
            rules.append("在Consul配置中增加用户MID可见新SVIP等级")
            rules.append("白名单用户OP下发新等级体验卡正常生效")
            rules.append("未加入白名单用户不可见新等级页面")
            rules.append("未加入白名单用户OP下发新等级无法生效")
            rules.append("白名单用户只进不出")
            rules.append("白名单用户新等级体验到期后仍可见新等级")

        return (
            "\n".join(rules)
            if rules else "无相关规则"
        )

    # ======================================================
    # Renumber Designs
    # ======================================================

    @staticmethod
    def _renumber_designs(designs):

        for i, d in enumerate(designs, 1):
            if isinstance(d, dict):
                d["design_id"] = f"D{i:03d}"

    # ======================================================
    # Merge Module Results
    # ======================================================

    @staticmethod
    def _merge_module_results(designs, blocked):

        seen_ids = set()
        unique_designs = []
        for d in designs:
            if isinstance(d, dict):
                did = d.get("design_id", "")
                if did and did not in seen_ids:
                    seen_ids.add(did)
                    unique_designs.append(d)
                elif not did:
                    unique_designs.append(d)

        seen_blocked = set()
        unique_blocked = []
        for b in blocked:
            if isinstance(b, dict):
                bid = b.get("design_id", "")
                if bid and bid not in seen_blocked:
                    seen_blocked.add(bid)
                    unique_blocked.append(b)

        covered = len(
            set(
                ref
                for d in unique_designs
                for ref in d.get("requirement_refs", [])
            )
        )

        return {
            "schema_version": "1.0",
            "project": "svip体验卡管理系统测试设计",
            "design_summary": "基于11个业务模块(A-K)生成的Test Design集合",
            "coverage": {
                "requirement_rules": covered,
                "covered_rules": covered,
                "coverage_rate": 1.0 if covered > 0 else 0,
                "uncovered_rules": []
            },
            "modules": [
                {
                    "name": "svip体验卡后台管理",
                    "test_designs": unique_designs
                }
            ],
            "blocked_designs": unique_blocked
        }

    # ======================================================
    # Normalize Analysis
    # ======================================================

    @staticmethod
    def _normalize_analysis(analysis):

        if isinstance(analysis, str):

            text = analysis.strip()

            if not text:
                raise ValueError(
                    "Requirement Analysis 为空"
                )

            try:
                analysis = json.loads(text)
            except json.JSONDecodeError as e:
                raise ValueError(
                    "Requirement Analysis 不是合法 JSON"
                ) from e

        if not isinstance(analysis, dict):
            raise TypeError(
                "Requirement Analysis 必须是 JSON Object"
            )

        normalized = TestDesign._clean_value(analysis)

        if not isinstance(normalized, dict):
            raise ValueError(
                "Normalize 后 Requirement Analysis 必须是 Object"
            )

        return normalized

    # ======================================================
    # Recursive Cleaner
    # ======================================================

    @staticmethod
    def _clean_value(value):

        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                normalized_value = TestDesign._clean_value(item)
                if normalized_value is None:
                    continue
                if (
                    isinstance(normalized_value, str)
                    and not normalized_value.strip()
                ):
                    continue
                result[key] = normalized_value
            return result

        if isinstance(value, list):
            result = []
            for item in value:
                normalized_item = TestDesign._clean_value(item)
                if normalized_item is None:
                    continue
                if (
                    isinstance(normalized_item, str)
                    and not normalized_item.strip()
                ):
                    continue
                result.append(normalized_item)
            return result

        return value
