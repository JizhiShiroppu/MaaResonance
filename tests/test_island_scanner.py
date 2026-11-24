import unittest

import numpy as np

from maa_resonance.logic.planning import (
    choose_best_island_invest_card,
    detect_island_monster_tap_points,
    evaluate_island_expand_safe,
    find_friend_list_visit_points,
    find_island_todo_claim_points,
    find_island_trash_collect_point,
    is_free_island_formation_entries,
    is_friend_island_entries,
    is_island_banner_entries,
    is_island_card_pack_entries,
    is_island_exchange_shop_entries,
    is_island_expand_modal_entries,
    is_island_friends_drawer_entries,
    is_island_main_entries,
    is_island_ops_invest_entries,
    is_island_ops_overview_entries,
    is_island_report_entries,
    is_island_todo_entries,
    is_island_trash_screen_entries,
    parse_friend_island_status,
    parse_island_exchange_shop,
    parse_island_expand_modal,
    parse_island_invest_cards,
    parse_island_main_hud,
    parse_island_ops_coins,
    parse_island_ops_invest,
    parse_island_ops_overview,
    parse_island_report_overview,
    parse_island_trash_screen,
)


class IslandScannerTest(unittest.TestCase):
    def test_page_recognizers_and_hud_parsers(self):
        self.assertTrue(is_island_banner_entries([{"text": "海岛入口"}]))
        top_e = [
            {"text": "装修商店", "center_x": 850, "center_y": 50},
            {"text": "70160", "center_x": 880, "center_y": 72},
            {"text": "海岛兑换处", "center_x": 1050, "center_y": 50},
            {"text": "40", "center_x": 1080, "center_y": 72},
            {"text": "事项一览", "center_x": 1180, "center_y": 152},
        ]
        dock_e = [
            {"text": "巡逻", "center_x": 665, "center_y": 640},
            {"text": "导航", "center_x": 785, "center_y": 640},
            {"text": "装修", "center_x": 910, "center_y": 640},
        ]
        self.assertTrue(is_island_main_entries(top_e, dock_e))
        hud = parse_island_main_hud(
            top_e,
            [{"text": "LV 14"}, {"text": "今日收益 2k"}],
            [
                {"text": "×42", "center_x": 295, "center_y": 665},
                {"text": "×11", "center_x": 355, "center_y": 665},
                {"text": "100%", "center_x": 417, "center_y": 665},
            ],
        )
        self.assertEqual(hud["level"], 14)
        self.assertEqual(hud["today_revenue_coins"], 2000)
        self.assertEqual(hud["visitors_current"], 42)
        self.assertEqual(hud["active_monsters"], 11)
        self.assertEqual(hud["cleanliness_pct"], 100)
        self.assertEqual(hud["material_tickets"], 70160)
        self.assertEqual(hud["shell_coins"], 40)

    def test_report_ops_and_invest_parsers(self):
        self.assertTrue(is_island_report_entries([{"text": "海岛经营报表"}, {"text": "稳定指数"}]))
        rep = parse_island_report_overview(
            [{"text": "海角等级 LV 14"}, {"text": "垃圾产出 87/h"}, {"text": "压缩垃圾数量 142"}],
            [
                {"text": "3579", "center_x": 680, "center_y": 238},
                {"text": "0", "center_x": 800, "center_y": 238},
                {"text": "0", "center_x": 925, "center_y": 238},
                {"text": "0", "center_x": 1045, "center_y": 238},
                {"text": "0", "center_x": 680, "center_y": 295},
                {"text": "527", "center_x": 800, "center_y": 295},
                {"text": "0", "center_x": 925, "center_y": 295},
                {"text": "100%", "center_x": 1045, "center_y": 295},
            ],
            [
                {"text": "805", "center_x": 570, "center_y": 420},
                {"text": "21855", "center_x": 780, "center_y": 420},
                {"text": "35/200", "center_x": 1020, "center_y": 420},
                {"text": "9", "center_x": 570, "center_y": 530},
                {"text": "3", "center_x": 780, "center_y": 530},
                {"text": "2", "center_x": 1020, "center_y": 530},
            ],
        )
        self.assertEqual(rep["level"], 14)
        self.assertEqual(rep["trash_rate_per_hour"], 87)
        self.assertEqual(rep["trash_blocks_stored"], 142)
        self.assertEqual(rep["scores"]["舒适"], 3579)
        self.assertEqual(rep["scores"]["美食"], 527)
        self.assertEqual(rep["stability_current"], 35)
        self.assertEqual(rep["stability_max"], 200)
        self.assertEqual(rep["cabin_level"], 3)
        self.assertEqual(rep["facilities_count"], 9)
        self.assertEqual(rep["decorations_count"], 2)

        self.assertTrue(
            is_island_ops_overview_entries(
                [{"text": "营收概览"}],
                [{"text": "当前营业概况"}, {"text": "当前分成比例 3.8%"}],
            )
        )
        ops = parse_island_ops_overview(
            [{"text": "01"}],
            [{"text": "当前分成比例 3.8% 当前票价 530 税率 4.7% 游客人数累计 21855"}],
            [{"text": "当前收益 125000"}, {"text": "收钱", "center_x": 1167, "center_y": 647}],
        )
        self.assertEqual(ops["avg_stay_days"], 1.0)
        self.assertAlmostEqual(ops["share_ratio_pct"], 3.8)
        self.assertEqual(ops["ticket_price"], 530)
        self.assertAlmostEqual(ops["tax_rate_pct"], 4.7)
        self.assertEqual(ops["pending_revenue_coins"], 125000)
        self.assertEqual(ops["collect_point"], (1167, 647))

        self.assertTrue(is_island_ops_invest_entries([{"text": "投资"}], [{"text": "剩余投资次数: 1"}]))
        inv = parse_island_ops_invest([{"text": "剩余投资次数: 1"}], [{"text": "340,000 已投资金额"}])
        self.assertEqual(inv, {"invest_remaining": 1, "invested_total": 340000})

    def test_trash_collect_guard_and_todo_guard(self):
        self.assertTrue(is_island_trash_screen_entries([{"text": "海岛垃圾产出总览"}]))
        trash = parse_island_trash_screen(
            [{"text": "总计: 87/h"}],
            [{"text": "待压缩垃圾数量: 57308"}],
            [{"text": "垃圾压缩机 LV 4"}],
            [{"text": "143/90"}],
        )
        self.assertEqual(trash["trash_rate_per_hour"], 87)
        self.assertEqual(trash["trash_pending_raw"], 57308)
        self.assertEqual(trash["trash_station_level"], 4)
        self.assertEqual(trash["trash_blocks_stored"], 143)
        self.assertEqual(trash["trash_blocks_cap"], 90)

        # 右侧一键收取放行；左侧一键处理或 X 偏左绝不命中
        self.assertEqual(
            find_island_trash_collect_point(
                [
                    {"text": "一键处理", "center_x": 1005, "center_y": 643},
                    {"text": "一键收取", "center_x": 1160, "center_y": 643},
                ]
            ),
            (1160, 643),
        )
        self.assertIsNone(
            find_island_trash_collect_point(
                [{"text": "一键处理", "center_x": 1005, "center_y": 643}]
            )
        )
        self.assertIsNone(
            find_island_trash_collect_point(
                [{"text": "一键收取", "center_x": 1005, "center_y": 643}]
            )
        )

        # 事项一览只允许点「领取/领奖」，绝不点「追踪」
        self.assertTrue(is_island_todo_entries([{"text": "海岛管理局"}, {"text": "海岛等级: 14"}]))
        pts = find_island_todo_claim_points(
            [
                {"text": "追踪", "center_x": 1190, "center_y": 140},
                {"text": "领取", "center_x": 1190, "center_y": 280},
                {"text": "追踪", "center_x": 1190, "center_y": 420},
                {"text": "领奖", "center_x": 1190, "center_y": 540},
            ]
        )
        self.assertEqual(pts, [(1190, 280), (1190, 540)])

    def test_friends_parser_formation_cost_and_monster_detector(self):
        self.assertTrue(is_island_friends_drawer_entries([{"text": "FRIEND LIST"}, {"text": "清扫"}, {"text": "治安"}]))
        visits = find_friend_list_visit_points(
            [
                {"text": "访问记录", "center_x": 500, "center_y": 148},
                {"text": "访问", "center_x": 507, "center_y": 237},
                {"text": "访问", "center_x": 507, "center_y": 330},
            ]
        )
        self.assertEqual(visits, [(507, 237), (507, 330)])

        self.assertTrue(
            is_friend_island_entries(
                [{"text": "帮助次数 5/5"}, {"text": "可被清理 3/3"}],
                [{"text": "清扫"}, {"text": "下一位"}],
            )
        )
        fst = parse_friend_island_status(
            [
                {"text": "5/5", "center_x": 890, "center_y": 78},
                {"text": "3/3", "center_x": 1010, "center_y": 78},
            ],
            [{"text": "無名吾妻", "center_x": 125, "center_y": 672}],
            [{"text": "×2", "center_x": 335, "center_y": 672}],
            [
                {"text": "清扫", "center_x": 740, "center_y": 640},
                {"text": "点赞", "center_x": 860, "center_y": 640},
                {"text": "下一位", "center_x": 1153, "center_y": 640},
            ],
        )
        self.assertEqual(fst["help_remaining"], 5)
        self.assertEqual(fst["clean_remaining"], 3)
        self.assertEqual(fst["friend_name"], "無名吾妻")
        self.assertEqual(fst["active_monsters"], 2)
        self.assertEqual(fst["clean_point"], (740, 640))

        self.assertTrue(is_free_island_formation_entries([{"text": "开始作战"}], [{"text": "-0"}]))
        self.assertFalse(is_free_island_formation_entries([{"text": "开始作战"}], [{"text": "-20"}]))

        # 构造 720p 合成图：中心放置一只红感叹号怪 [620..660, 290..330]，右上/底部放置被排除的假红块
        img = np.full((720, 1280, 3), 210, dtype=np.uint8)
        # 有效红 [!] 徽章（BGR 珊瑚红 (110, 120, 240) + 白感叹号）
        img[290:330, 620:660] = (110, 120, 240)
        img[296:322, 632:648] = (245, 245, 245)
        # 左上顶栏排除区假红块
        img[20:55, 620:660] = (110, 120, 240)
        img[26:48, 632:648] = (245, 245, 245)
        pts = detect_island_monster_tap_points(img)
        self.assertEqual(len(pts), 1)
        self.assertTrue(630 <= pts[0][0] <= 650)
        self.assertTrue(355 <= pts[0][1] <= 380)

    def test_real_mumu_1551_ocr_regression(self):
        hud = parse_island_main_hud(
            top_entries=[],
            left_entries=[
                {"box": [17, 626, 46, 27], "score": 0.882649, "text": "v14"},
                {"box": [134, 629, 65, 20], "score": 0.986503, "text": "今日收益"},
                {"box": [136, 657, 45, 22], "score": 0.781243, "text": "0"},
                {"box": [202, 634, 20, 12], "score": 0.968660, "text": "2k"},
            ],
            counts_entries=[
                {"box": [283, 651, 30, 15], "text": "×42"},
                {"box": [345, 651, 28, 15], "text": "×11"},
                {"box": [400, 651, 38, 15], "text": "100%"},
            ],
            ticket_entries=[
                {"box": [824, 57, 5, 8], "score": 0.079606, "text": "2"},
                {"box": [824, 68, 5, 8], "score": 0.166545, "text": "7"},
                {"box": [849, 55, 36, 8], "score": 0.377926, "text": "表定险"},
                {"box": [860, 67, 57, 14], "score": 0.997266, "text": "70160"},
            ],
            shell_entries=[
                {"box": [1055, 67, 24, 14], "score": 0.99, "text": "40"},
            ],
        )
        self.assertEqual(hud["material_tickets"], 70160)
        self.assertEqual(hud["shell_coins"], 40)
        self.assertEqual(hud["level"], 14)
        self.assertEqual(hud["today_revenue_coins"], 2000)

        rep = parse_island_report_overview(
            left_entries=[
                {"box": [172, 413, 97, 29], "text": "|海岛环境"},
                {"box": [189, 360, 80, 18], "text": "海角等级"},
                {"box": [360, 519, 115, 25], "text": "压缩垃圾数量"},
                {"box": [395, 451, 82, 29], "text": "垃圾产出"},
                {"box": [424, 365, 53, 28], "text": "LV14"},
                {"box": [426, 476, 53, 27], "text": "87/h"},
                {"box": [435, 541, 42, 29], "text": "144"},
            ],
            scores_entries=[],
            basic_entries=[],
        )
        self.assertEqual(rep["level"], 14)
        self.assertEqual(rep["trash_rate_per_hour"], 87)
        self.assertEqual(rep["trash_blocks_stored"], 144)

        ops = parse_island_ops_overview(
            [{"text": "01"}],
            [
                {"box": [626, 226, 97, 19], "text": "当前分成比例"},
                {"box": [682, 343, 73, 24], "text": "额外分成"},
                {"box": [683, 307, 72, 22], "text": "基本分成"},
                {"box": [689, 363, 58, 30], "text": "0.8%"},
                {"box": [698, 275, 42, 36], "text": "3%"},
                {"box": [762, 221, 52, 30], "text": "3.8%"},
                {"box": [844, 224, 95, 21], "text": "当前票价"},
                {"box": [910, 275, 104, 21], "text": "游客人数累计"},
                {"box": [994, 223, 38, 23], "text": "530"},
                {"box": [1049, 221, 71, 29], "text": "税率"},
                {"box": [1120, 272, 83, 38], "text": "21855"},
                {"box": [1169, 364, 40, 23], "text": "散客"},
                {"box": [1184, 222, 51, 26], "text": "4.7%"},
            ],
            [],
        )
        self.assertAlmostEqual(ops["share_ratio_pct"], 3.8)
        self.assertEqual(ops["ticket_price"], 530)
        self.assertAlmostEqual(ops["tax_rate_pct"], 4.7)
        self.assertEqual(ops["total_visitors"], 21855)

    def test_real_mumu_1608_1613_friend_and_report_regression(self):
        self.assertTrue(is_island_friends_drawer_entries([{"text": "好友"}, {"text": "清扫"}]))
        self.assertTrue(
            is_friend_island_entries(
                [{"text": "可被洁理"}, {"text": "获得垃圾概率"}],
                [{"text": "清扫"}],
            )
        )

        clean_dash_before = [
            {"box": [848, 67, 54, 16], "score": 0.999635, "text": "帮助次数"},
            {"box": [850, 90, 74, 46], "score": 0.975465, "text": "5/5"},
            {"box": [978, 69, 53, 12], "score": 0.976984, "text": "可被洁理"},
            {"box": [979, 93, 70, 39], "score": 0.995268, "text": "3/3"},
        ]
        clean_dash_after = [
            {"box": [848, 67, 54, 16], "score": 0.999635, "text": "帮助次数"},
            {"box": [852, 93, 69, 39], "score": 0.984951, "text": "5/5"},
            {"box": [977, 68, 54, 12], "score": 0.986738, "text": "可被洁理"},
            {"box": [979, 93, 70, 39], "score": 0.995109, "text": "2/3"},
        ]
        cinfo0 = [
            {"box": [19, 628, 43, 25], "score": 0.884531, "text": "Lv33"},
            {"box": [20, 648, 48, 44], "score": 0.153279, "text": "*"},
            {"box": [114, 656, 84, 25], "score": 0.997158, "text": "無名吾妻"},
        ]
        cinfo1 = [
            {"box": [15, 645, 57, 48], "score": 0.162916, "text": "*"},
            {"box": [17, 625, 46, 30], "score": 0.954306, "text": "Lv31"},
            {"box": [120, 658, 71, 22], "score": 0.984660, "text": "zhynull"},
        ]
        sinfo0 = [
            {"box": [18, 627, 45, 26], "score": 0.829541, "text": "v14"},
            {"box": [24, 652, 41, 29], "score": 0.119838, "text": "果"},
            {"box": [110, 659, 93, 21], "score": 0.997185, "text": "Ozoraore"},
        ]
        sinfo1 = [
            {"box": [15, 624, 48, 32], "score": 0.928256, "text": "Lv31"},
            {"box": [21, 649, 46, 41], "score": 0.120624, "text": "果"},
            {"box": [119, 656, 73, 25], "score": 0.994384, "text": "zhynull"},
        ]

        st0 = parse_friend_island_status(clean_dash_before, cinfo0, [], [])
        st0_after = parse_friend_island_status(clean_dash_after, cinfo0, [], [])
        st1 = parse_friend_island_status(clean_dash_before, cinfo1, [], [])
        sts0 = parse_friend_island_status(clean_dash_before, sinfo0, [], [])
        sts1 = parse_friend_island_status(clean_dash_before, sinfo1, [], [])
        self.assertEqual(st0["friend_name"], "無名吾妻")
        self.assertTrue(st0["clean_remaining_known"])
        self.assertEqual(st0["clean_remaining"], 3)
        self.assertEqual(st0_after["clean_remaining"], 2)
        self.assertEqual(st1["friend_name"], "zhynull")
        self.assertEqual(sts0["friend_name"], "Ozoraore")
        self.assertEqual(sts1["friend_name"], "zhynull")

        empty_dash = parse_friend_island_status([], sinfo0, [], [])
        self.assertFalse(empty_dash["clean_remaining_known"])
        self.assertFalse(empty_dash["help_remaining_known"])

        rep_basic_1611 = [
            {"box": [513, 409, 78, 25], "score": 0.999921, "text": "经营天数"},
            {"box": [514, 433, 40, 23], "score": 0.999046, "text": "806"},
            {"box": [514, 518, 76, 24], "score": 0.999874, "text": "设施数量"},
            {"box": [516, 545, 13, 18], "score": 0.987889, "text": "9"},
            {"box": [717, 520, 77, 23], "score": 0.999887, "text": "木屋等级"},
            {"box": [718, 408, 77, 25], "score": 0.999751, "text": "游客人数"},
            {"box": [718, 432, 60, 24], "score": 0.999437, "text": "21855"},
            {"box": [719, 545, 12, 18], "score": 0.996246, "text": "3"},
            {"box": [840, 387, 13, 9], "score": 0.242792, "text": "c"},
            {"box": [851, 377, 9, 6], "score": 0.192979, "text": "2"},
            {"box": [926, 410, 75, 22], "score": 0.999910, "text": "稳定指数"},
            {"box": [926, 434, 67, 22], "score": 0.998899, "text": "35/200"},
            {"box": [927, 520, 77, 23], "score": 0.999789, "text": "装饰数量"},
            {"box": [927, 544, 16, 20], "score": 0.993185, "text": "2"},
        ]
        rep = parse_island_report_overview([], [], rep_basic_1611)
        self.assertEqual(rep["total_visitors"], 21855)
        self.assertEqual(rep["operating_days"], 806)
        self.assertEqual(rep["cabin_level"], 3)

    def test_monster_detector_1080p_scaling_and_false_positive_rejection(self):
        img = np.full((1080, 1920, 3), 210, dtype=np.uint8)
        # 1) 中央前景大红 [!!] 徽章（1080p 100x110）
        img[495:605, 910:1010] = (122, 128, 252)
        img[515:585, 940:980] = (245, 245, 245)
        # 2) 排球妹粉发误触噪声（无内部白叹号）
        img[360:435, 580:655] = (140, 145, 250)
        # 3) 深红西瓜噪声（高饱和红且无白叹号）
        img[420:510, 1400:1490] = (55, 55, 235)
        # 4) 最右侧边缘 [!!] 徽章（应排在中央之后）
        img[520:610, 1815:1895] = (122, 128, 252)
        img[535:590, 1840:1870] = (245, 245, 245)

        pts = detect_island_monster_tap_points(img)
        self.assertEqual(len(pts), 2)
        self.assertTrue(620 <= pts[0][0] <= 660)
        self.assertTrue(440 <= pts[0][1] <= 475)
        self.assertGreaterEqual(pts[1][0], 1200)


class IslandPlanActionSocialAndRetryTests(unittest.TestCase):
    def test_drawer_retry_and_secflow_visits_with_noisy_avatar_info(self):
        try:
            import agent.island_plan_action as ipa
        except ModuleNotFoundError:
            self.skipTest("maafw is not installed")
        from unittest.mock import patch
        from maa_resonance.logic.planning import (
            ISLAND_FRIENDS_CLEAN_TAB_POINT,
            ISLAND_FRIENDS_SECURITY_TAB_POINT,
            ISLAND_SKY_DISMISS_POINT,
            IslandDiagnosticRecorder,
            IslandRuntimeConfig,
        )

        tapped: list[tuple[str, tuple[int, int]]] = []
        dummy_img = np.zeros((720, 1280, 3), dtype=np.uint8)
        drawer_hdr_calls = {"count": 0}

        def fake_tap(_ctx, name, pt):
            tapped.append((name, tuple(pt)))
            return True

        def fake_ocr_drawer(_ctx, _img, node_name, _roi):
            if "Chk" in node_name:
                if node_name.endswith("Chk0"):
                    return [{"text": "装修商店", "box": [846, 48, 56, 16]}] if "Top" in node_name else [{"text": "巡逻", "box": [635, 652, 50, 20]}]
                return []
            if "FHdr" in node_name:
                drawer_hdr_calls["count"] += 1
                if drawer_hdr_calls["count"] <= 2:
                    return [{"text": "管理中心", "box": [294, 111, 114, 37]}]
                return [{"text": "好友", "box": [232, 54, 60, 32]}, {"text": "清扫", "box": [291, 139, 33, 20]}]
            if "List" in node_name:
                return [{"text": "访问", "center_x": 514, "center_y": 250}]
            if "FDash" in node_name:
                return [{"text": "帮助次数 5/5"}, {"text": "可被清理 3/3"}]
            if "FBot" in node_name:
                return [{"text": "清扫"}, {"text": "下一位"}]
            return []

        diag = IslandDiagnosticRecorder(export_mode="log_only")
        with (
            patch.object(ipa, "safe_screencap", return_value=dummy_img),
            patch.object(ipa, "sleep_with_stop", return_value=True),
            patch.object(ipa, "is_stopping", return_value=False),
            patch.object(ipa, "_ensure_on_island_main", return_value=True),
            patch.object(ipa, "tap_point", side_effect=fake_tap),
            patch.object(ipa, "ocr_roi", side_effect=fake_ocr_drawer),
        ):
            ok = ipa._open_friends_drawer_and_visit_first(
                None,
                "RetryT",
                ISLAND_FRIENDS_CLEAN_TAB_POINT,
                diag=diag,
            )
        self.assertTrue(ok)
        self.assertIn(("RetryTDrawerSkyDismiss", ISLAND_SKY_DISMISS_POINT), tapped)

        # 验证 SecFlow 模式下即使首个好友头像带噪声"果"仍正常推进至第2位并统计 Visits>=2
        tapped.clear()
        visit_idx = {"i": -1}

        def fake_ocr_sec(_ctx, _img, node_name, _roi):
            if "Top" in node_name:
                return [{"text": "装修商店"}, {"text": "管理中心"}]
            if "Dock" in node_name:
                return [{"text": "巡逻"}, {"text": "导航"}]
            if "FHdr" in node_name:
                return [{"text": "好友"}, {"text": "治安"}]
            if "List" in node_name:
                return [{"text": "访问", "center_x": 514, "center_y": 250}]
            if node_name.endswith(("FDash", "Chk0Dash", "Chk1Dash")) or "Dash" in node_name:
                return [
                    {"box": [850, 90, 74, 46], "text": "5/5" if visit_idx["i"] <= 0 else "4/5"},
                    {"box": [979, 93, 70, 39], "text": "3/3"},
                    {"text": "可被洁理"},
                ]
            if "Bot" in node_name:
                return [
                    {"text": "清扫", "center_x": 740, "center_y": 664},
                    {"text": "点赞", "center_x": 860, "center_y": 664},
                    {"text": "下一位", "center_x": 1154, "center_y": 656},
                ]
            if "Info" in node_name:
                cur_name = "Ozoraore" if visit_idx["i"] <= 0 else "zhynull"
                return [
                    {"box": [24, 652, 41, 29], "score": 0.12, "text": "果"},
                    {"box": [110, 659, 93, 21], "score": 0.99, "text": cur_name},
                ]
            if "Cnt" in node_name:
                return [{"text": "×0" if visit_idx["i"] <= 0 else "×2"}]
            return []

        def fake_tap_sec(_ctx, name, pt):
            tapped.append((name, tuple(pt)))
            if "VisitFirst" in name:
                visit_idx["i"] = 0
            elif "Next" in name:
                visit_idx["i"] += 1
            return True

        state = ipa._IslandExecState()
        cfg = IslandRuntimeConfig(
            exec_mode="execute_safe_auto",
            auto_scope="custom",
            enabled_modules=frozenset({"friend_help_monsters"}),
            max_friend_visits=3,
            max_friend_help_fights=1,
        )
        diag2 = IslandDiagnosticRecorder(export_mode="log_only")
        with (
            patch.object(ipa, "safe_screencap", return_value=dummy_img),
            patch.object(ipa, "sleep_with_stop", return_value=True),
            patch.object(ipa, "is_stopping", return_value=False),
            patch.object(ipa, "_ensure_on_island_main", return_value=True),
            patch.object(ipa, "tap_point", side_effect=fake_tap_sec),
            patch.object(ipa, "ocr_roi", side_effect=fake_ocr_sec),
            patch.object(ipa, "detect_island_monster_tap_points", return_value=[(640, 400)]),
            patch.object(ipa, "_try_enter_and_fight_monster", return_value=(True, True, "ok")),
        ):
            ipa._exec_friends_social_routine(None, "SecT", runtime_cfg=cfg, state=state, diag=diag2)

        self.assertEqual(state.friend_visits, 2)
        self.assertEqual(state.friend_monsters_helped, 1)
        self.assertTrue(any(ev["stage"] == "friends_social" and ev["event"] == "summary" for ev in diag2.events))
        self.assertIn(("SecTPass1SelectTab", ISLAND_FRIENDS_SECURITY_TAB_POINT), tapped)


class IslandStage2PolishAndStage3ATests(unittest.TestCase):
    def test_report_overview_rejects_high_score_icon_noise_and_hud_bare_level(self):
        rep_basic_with_icon_noise = [
            {"box": [851, 377, 9, 6], "score": 0.96, "text": "2"},
            {"box": [620, 480, 12, 12], "score": 0.95, "text": "8"},
            {"box": [514, 433, 40, 23], "score": 0.99, "text": "806"},
            {"box": [718, 432, 60, 24], "score": 0.99, "text": "21855"},
            {"box": [926, 434, 67, 22], "score": 0.99, "text": "35/200"},
            {"box": [516, 545, 13, 18], "score": 0.99, "text": "9"},
            {"box": [719, 545, 12, 18], "score": 0.99, "text": "3"},
            {"box": [927, 544, 16, 20], "score": 0.99, "text": "2"},
        ]
        rep = parse_island_report_overview([], [], rep_basic_with_icon_noise)
        self.assertEqual(rep["total_visitors"], 21855)
        self.assertEqual(rep["operating_days"], 806)
        self.assertEqual(rep["facilities_count"], 9)
        self.assertEqual(rep["cabin_level"], 3)

        hud = parse_island_main_hud(
            [],
            [
                {"box": [24, 632, 26, 20], "score": 0.98, "text": "14"},
                {"box": [110, 625, 65, 22], "score": 0.99, "text": "今日收益"},
                {"box": [182, 625, 42, 22], "score": 0.99, "text": "2k"},
            ],
            [],
        )
        self.assertEqual(hud["level"], 14)
        self.assertEqual(hud["today_revenue_coins"], 2000)

    def test_invest_cards_parser_priority_and_guards(self):
        self.assertEqual(parse_island_ops_coins([{"text": "46991972+", "score": 0.99}]), 46_991_972)
        cards_entries = [
            {"text": "+0.4%", "center_x": 714, "center_y": 385, "score": 0.99},
            {"text": "分成比例提高0.4%", "center_x": 714, "center_y": 465, "score": 0.99},
            {"text": "40000", "center_x": 714, "center_y": 607, "score": 0.99},
            {"text": "+0.6%", "center_x": 932, "center_y": 385, "score": 0.99},
            {"text": "分成比例提高0.6%", "center_x": 932, "center_y": 465, "score": 0.99},
            {"text": "60000", "center_x": 932, "center_y": 607, "score": 0.99},
            {"text": "+20", "center_x": 1152, "center_y": 385, "score": 0.99},
            {"text": "票价提升20", "center_x": 1152, "center_y": 465, "score": 0.99},
            {"text": "120000", "center_x": 1152, "center_y": 607, "score": 0.99},
        ]
        cards = parse_island_invest_cards(cards_entries)
        self.assertEqual(len(cards), 3)
        self.assertEqual(cards[1]["kind"], "share_ratio")
        self.assertEqual(cards[1]["cost_coins"], 60000)
        self.assertEqual(cards[2]["kind"], "ticket_price")

        # 预算充足优先选分成提高最多(+0.6% / 60000)
        chosen, reason = choose_best_island_invest_card(
            cards, spendable_coins=500_000, share_ratio_pct=5.0, ticket_price=500, tax_rate_pct=4.5
        )
        self.assertEqual(reason, "ok")
        self.assertEqual(chosen["col"], 1)

        # 预算卡在 50,000 时退而选 Col 0(40,000)
        chosen2, reason2 = choose_best_island_invest_card(cards, spendable_coins=50_000, share_ratio_pct=5.0)
        self.assertEqual(reason2, "ok")
        self.assertEqual(chosen2["col"], 0)

        # 预算 10,000 时触发底线拒绝
        chosen3, reason3 = choose_best_island_invest_card(cards, spendable_coins=10_000, share_ratio_pct=5.0)
        self.assertIsNone(chosen3)
        self.assertEqual(reason3, "exceeds_reserve")

        # 分成已达 35% 上限时改投 +20 票价
        chosen4, reason4 = choose_best_island_invest_card(cards, spendable_coins=500_000, share_ratio_pct=35.0, ticket_price=500)
        self.assertEqual(reason4, "ok")
        self.assertEqual(chosen4["kind"], "ticket_price")

        # 含桦石词卡片必须被硬拒绝
        hua_cards = parse_island_invest_cards(
            [
                {"text": "分成比例+1%", "center_x": 714, "center_y": 420},
                {"text": "桦石", "center_x": 714, "center_y": 570},
                {"text": "100", "center_x": 714, "center_y": 607},
            ]
        )
        chosen5, reason5 = choose_best_island_invest_card(hua_cards, spendable_coins=500_000)
        self.assertIsNone(chosen5)
        self.assertEqual(reason5, "no_eligible_card")

        # 实机 17:26 投资卡片回归：顶栏描述"投资120000铁盟币 获得20票价奖励"不误取 120000，底部图标噪声 "2" 不盖过 "40000"
        real_cards = parse_island_invest_cards(
            [
                {"text": "投资40000铁盟币 获得0.4%分成奖励", "center_x": 714, "center_y": 395, "score": 0.99},
                {"text": "2", "center_x": 674, "center_y": 650, "score": 0.72},
                {"text": "40000", "center_x": 714, "center_y": 649, "score": 0.99},
                {"text": "投资120000铁盟币 获得20票价奖励", "center_x": 1152, "center_y": 395, "score": 0.99},
                {"text": "120000", "center_x": 1162, "center_y": 649, "score": 0.99},
            ]
        )
        self.assertEqual(real_cards[0]["cost_coins"], 40000)
        self.assertEqual(real_cards[0]["benefit_value"], 0.4)
        self.assertEqual(real_cards[0]["tap_point"], (714, 649))
        self.assertEqual(real_cards[1]["kind"], "ticket_price")
        self.assertEqual(real_cards[1]["benefit_value"], 20.0)
        self.assertEqual(real_cards[1]["cost_coins"], 120000)

    def test_expand_modal_parser_and_safety_guards(self):
        modal_e = [
            {"text": "海岛扩建", "center_x": 640, "center_y": 150},
            {"text": "是否确认解锁02号岛?", "center_x": 640, "center_y": 210},
            {"text": "46M/600K", "center_x": 510, "center_y": 350},
            {"text": "70K/6K", "center_x": 770, "center_y": 350},
            {"text": "需求：海岛LV6", "center_x": 640, "center_y": 420},
        ]
        btn_e = [
            {"text": "取消", "center_x": 320, "center_y": 545},
            {"text": "确认", "center_x": 960, "center_y": 545},
        ]
        self.assertTrue(is_island_expand_modal_entries(modal_e))
        parsed = parse_island_expand_modal(modal_e, btn_e)
        self.assertEqual(parsed["required_level"], 6)
        self.assertEqual(parsed["cost_coins"], 600_000)
        self.assertEqual(parsed["cost_tickets"], 6_000)
        self.assertEqual(parsed["confirm_point"], (960, 545))

        ok, _ = evaluate_island_expand_safe(
            parsed, current_level=14, live_coins=47_000_000, live_tickets=80_000, reserve_coins=15_000_000
        )
        self.assertTrue(ok)

        ok_res, r_res = evaluate_island_expand_safe(
            parsed, current_level=14, live_coins=15_200_000, live_tickets=80_000, reserve_coins=15_000_000
        )
        self.assertFalse(ok_res)
        self.assertIn("底线", r_res)

        ok_lv, r_lv = evaluate_island_expand_safe(
            parsed, current_level=5, live_coins=47_000_000, live_tickets=80_000, reserve_coins=15_000_000
        )
        self.assertFalse(ok_lv)
        self.assertIn("等级", r_lv)

        ok_tkt, r_tkt = evaluate_island_expand_safe(
            parsed, current_level=14, live_coins=47_000_000, live_tickets=5_000, reserve_coins=15_000_000
        )
        self.assertFalse(ok_tkt)
        self.assertIn("资材券", r_tkt)

        parsed_no_confirm = parse_island_expand_modal(modal_e, [{"text": "取消", "center_x": 320, "center_y": 545}])
        ok_nc, r_nc = evaluate_island_expand_safe(
            parsed_no_confirm, current_level=14, live_coins=47_000_000, live_tickets=80_000, reserve_coins=15_000_000
        )
        self.assertFalse(ok_nc)
        self.assertIn("确认按钮", r_nc)

        parsed_hua = parse_island_expand_modal(modal_e + [{"text": "消耗桦石50", "center_x": 640, "center_y": 300}], btn_e)
        ok_h, r_h = evaluate_island_expand_safe(
            parsed_hua, current_level=14, live_coins=47_000_000, live_tickets=80_000, reserve_coins=15_000_000
        )
        self.assertFalse(ok_h)
        self.assertIn("桦石", r_h)

    def test_exchange_shop_readonly_parser(self):
        self.assertTrue(is_island_exchange_shop_entries([{"text": "海岛兑换"}], []))
        cur_e = [
            {"text": "46991972+", "center_x": 760, "center_y": 32, "score": 0.99},
            {"text": "0", "center_x": 960, "center_y": 32, "score": 0.95},
            {"text": "130", "center_x": 1180, "center_y": 32, "score": 0.99},
        ]
        list_e = [
            {"text": "沙滩比赛用球x1", "center_x": 760, "center_y": 195, "score": 0.99},
            {"text": "剩余20次", "center_x": 760, "center_y": 230, "score": 0.99},
            {"text": "130/20", "center_x": 1140, "center_y": 215, "score": 0.99},
            {"text": "喧闹摇滚x1", "center_x": 760, "center_y": 345, "score": 0.99},
            {"text": "剩余1次", "center_x": 760, "center_y": 380, "score": 0.99},
            {"text": "130/1k", "center_x": 1140, "center_y": 365, "score": 0.99},
            {"text": "拉普拉斯协议x1", "center_x": 760, "center_y": 495, "score": 0.99},
            {"text": "剩余5次", "center_x": 760, "center_y": 530, "score": 0.99},
            {"text": "0/200", "center_x": 1140, "center_y": 515, "score": 0.99},
        ]
        # 附加顶部无价标签"福礼"及跨度 72px 的"剩余5次"应干净过滤与归并
        list_e_with_noise = [
            {"text": "福礼", "center_x": 650, "center_y": 152, "score": 0.98},
            *list_e,
        ]
        parsed = parse_island_exchange_shop(cur_e, list_e_with_noise)
        self.assertEqual(parsed["coins"], 46_991_972)
        self.assertEqual(parsed["volleyball_coins"], 0)
        self.assertEqual(parsed["shell_coins"], 130)
        self.assertEqual(len(parsed["items"]), 3)
        self.assertEqual(parsed["items"][0]["name"], "沙滩比赛用球x1")
        self.assertTrue(parsed["items"][0]["affordable"])
        self.assertEqual(parsed["items"][1]["cost"], 1000)
        self.assertFalse(parsed["items"][1]["affordable"])
        self.assertEqual(parsed["items"][2]["remaining"], 5)

    def test_clear_own_monsters_retry_and_stage3a_action_mocks(self):
        try:
            import agent.island_plan_action as ipa
        except ModuleNotFoundError:
            self.skipTest("maafw is not installed")
        from unittest.mock import patch
        from maa_resonance.logic.planning import (
            ISLAND_EXPAND_CANCEL_FALLBACK,
            IslandDiagnosticRecorder,
        )

        dummy_img = np.zeros((720, 1280, 3), dtype=np.uint8)

        # 1) 1 次偶发未命中不应烧掉击杀配额，max_fights=3 仍完整打出 3 胜
        state_mob = ipa._IslandExecState()
        diag_mob = IslandDiagnosticRecorder(export_mode="log_only")
        battle_outcomes = iter([(False, False, "not_free_formation"), (True, True, "ok"), (True, True, "ok"), (True, True, "ok")])
        with (
            patch.object(ipa, "safe_screencap", return_value=dummy_img),
            patch.object(ipa, "sleep_with_stop", return_value=True),
            patch.object(ipa, "is_stopping", return_value=False),
            patch.object(ipa, "_ensure_on_island_main", return_value=True),
            patch.object(ipa, "_read_live_own_monster_count", return_value=5),
            patch.object(ipa, "tap_point", return_value=True),
            patch.object(ipa, "detect_island_monster_tap_points", return_value=[(640, 400)]),
            patch.object(ipa, "_try_enter_and_fight_monster", side_effect=lambda *_a, **_kw: next(battle_outcomes)),
        ):
            cleared = ipa._exec_clear_own_monsters(
                None,
                "MobRetry",
                max_fights=3,
                stability_current=35,
                stability_max=200,
                active_monsters=9,
                state=state_mob,
                diag=diag_mob,
            )
        self.assertEqual(cleared, 3)
        self.assertEqual(state_mob.own_monsters_cleared, 3)

        # 2) _scan_and_maybe_expand_island: PlanOnly (allow_execute=False) 和低于底线时一律点取消、零花费
        tapped_exp: list[tuple[str, tuple[int, int]]] = []

        def fake_ocr_exp(_ctx, _img, node_name, _roi):
            if "ExpChk" in node_name or "ExpModal" in node_name:
                return [
                    {"text": "海岛扩建", "center_x": 640, "center_y": 150},
                    {"text": "46M/600K", "center_x": 510, "center_y": 350},
                    {"text": "70K/6K", "center_x": 770, "center_y": 350},
                    {"text": "需求：海岛LV6", "center_x": 640, "center_y": 420},
                ]
            if "ExpBtns" in node_name:
                return [
                    {"text": "取消", "center_x": 320, "center_y": 545},
                    {"text": "确认", "center_x": 960, "center_y": 545},
                ]
            return []

        state_exp = ipa._IslandExecState()
        with (
            patch.object(ipa, "safe_screencap", return_value=dummy_img),
            patch.object(ipa, "sleep_with_stop", return_value=True),
            patch.object(ipa, "_ensure_on_island_main", return_value=True),
            patch.object(ipa, "tap_point", side_effect=lambda _c, n, p: tapped_exp.append((n, tuple(p))) or True),
            patch.object(ipa, "ocr_roi", side_effect=fake_ocr_exp),
        ):
            ipa._scan_and_maybe_expand_island(
                None,
                "ExpRO",
                allow_execute=False,
                current_level=14,
                live_coins=47_000_000,
                live_tickets=80_000,
                reserve_coins=15_000_000,
                state=state_exp,
            )
            self.assertEqual(state_exp.islands_expanded, 0)
            self.assertIn(("ExpROExpReadOnlyCancel", ISLAND_EXPAND_CANCEL_FALLBACK), tapped_exp)

            tapped_exp.clear()
            ipa._scan_and_maybe_expand_island(
                None,
                "ExpRes",
                allow_execute=True,
                current_level=14,
                live_coins=15_100_000,
                live_tickets=80_000,
                reserve_coins=15_000_000,
                state=state_exp,
            )
            self.assertEqual(state_exp.islands_expanded, 0)
            self.assertEqual(len(state_exp.skipped), 1)
            self.assertIn(("ExpResExpGuardCancel", ISLAND_EXPAND_CANCEL_FALLBACK), tapped_exp)

        # 3) _scan_and_maybe_claim_ops(auto_invest=True) 核验执行 1 次投资并正确记账 60000 币
        invest_step = {"done": False}
        tapped_inv: list[tuple[str, tuple[int, int]]] = []

        def fake_tap_inv(_ctx, name, pt):
            tapped_inv.append((name, tuple(pt)))
            if "ExecInv" in name:
                invest_step["done"] = True
            return True

        def fake_ocr_inv(_ctx, _img, node_name, _roi):
            if "OpsTab" in node_name or "OpsMetrics" in node_name or "OpsBody" in node_name:
                return [
                    {"text": "营收概览", "center_x": 767, "center_y": 103},
                    {"text": "当前分成比例", "center_x": 750, "center_y": 210},
                    {"text": "10%", "center_x": 760, "center_y": 230},
                ]
            if "InvTab" in node_name:
                return [{"text": "投资", "center_x": 1093, "center_y": 103}]
            if "InvSum" in node_name or "InvAfterSum" in node_name:
                amt = "400000" if invest_step["done"] else "340000"
                return [{"text": "已投资金额"}, {"text": amt}]
            if "InvRem" in node_name or "InvAfterRem" in node_name:
                rem_txt = "剩余投资次数：0" if invest_step["done"] else "剩余投资次数：1"
                return [{"text": rem_txt}]
            if "InvCoins" in node_name or "InvAfterCoins" in node_name:
                coins_txt = "46931972+" if invest_step["done"] else "46991972+"
                return [{"text": coins_txt, "score": 0.99}]
            if "InvCards" in node_name or "InvAfterCards" in node_name:
                return [
                    {"text": "+0.4%", "center_x": 714, "center_y": 385, "score": 0.99},
                    {"text": "分成比例提高0.4%", "center_x": 714, "center_y": 465, "score": 0.99},
                    {"text": "40000", "center_x": 714, "center_y": 607, "score": 0.99},
                    {"text": "+0.6%", "center_x": 932, "center_y": 385, "score": 0.99},
                    {"text": "分成比例提高0.6%", "center_x": 932, "center_y": 465, "score": 0.99},
                    {"text": "60000", "center_x": 932, "center_y": 607, "score": 0.99},
                ]
            return []

        state_inv = ipa._IslandExecState()
        with (
            patch.object(ipa, "safe_screencap", return_value=dummy_img),
            patch.object(ipa, "sleep_with_stop", return_value=True),
            patch.object(ipa, "is_stopping", return_value=False),
            patch.object(ipa, "_ensure_on_island_main", return_value=True),
            patch.object(ipa, "dismiss_reward_popup_if_present", return_value=True),
            patch.object(ipa, "tap_point", side_effect=fake_tap_inv),
            patch.object(ipa, "ocr_roi", side_effect=fake_ocr_inv),
        ):
            _, inv_res = ipa._scan_and_maybe_claim_ops(
                None,
                "InvTest",
                claim_revenue=False,
                auto_invest=True,
                reserve_coins=15_000_000,
                coins_budget=46_991_972,
                state=state_inv,
            )
        self.assertEqual(state_inv.invest_executed_count, 1)
        self.assertEqual(state_inv.invest_spent_coins, 60_000)
        self.assertEqual(inv_res["invest_remaining"], 0)
        self.assertEqual(inv_res["invested_total"], 400_000)
        self.assertIn(("InvTestExecInv0", (932, 607)), tapped_inv)

    def test_claim_todo_circle_offset_and_unchanged_stop(self):
        try:
            import agent.island_plan_action as ipa
        except ModuleNotFoundError:
            self.skipTest("maafw is not installed")
        from unittest.mock import patch
        from maa_resonance.logic.planning import (
            IslandDiagnosticRecorder,
            island_todo_claim_circle_point,
        )

        self.assertEqual(island_todo_claim_circle_point((1211, 134)), (1211, 102))

        dummy_img = np.zeros((720, 1280, 3), dtype=np.uint8)

        # 场景 A：点击圆钮和文字区均无任何状态变化（还原 18:02 连点 8 次场景）-> 仅点 2 次即中止并记 0 次领取
        tapped_a: list[tuple[str, tuple[int, int]]] = []

        def fake_ocr_unchanged(_ctx, _img, node_name, _roi):
            if "TodoBtns" in node_name or "TodoChk" in node_name:
                return [{"text": "领取", "center_x": 1211, "center_y": 134}]
            if "TodoLvl" in node_name:
                return [{"text": "海岛等级：16"}]
            if "TodoTitles" in node_name:
                return [{"text": "【海岛度假物语】将木屋升级到LV4"}]
            return []

        state_a = ipa._IslandExecState()
        diag_a = IslandDiagnosticRecorder(export_mode="log_only")
        with (
            patch.object(ipa, "safe_screencap", return_value=dummy_img),
            patch.object(ipa, "sleep_with_stop", return_value=True),
            patch.object(ipa, "is_stopping", return_value=False),
            patch.object(ipa, "_ensure_on_island_main", return_value=True),
            patch.object(ipa, "dismiss_reward_popup_if_present", return_value=True),
            patch.object(ipa, "tap_point", side_effect=lambda _c, n, p: tapped_a.append((n, tuple(p))) or True),
            patch.object(ipa, "ocr_roi", side_effect=fake_ocr_unchanged),
        ):
            claimed_a = ipa._exec_claim_todo_rewards(None, "TodoUnchg", state_a, diag=diag_a)

        self.assertEqual(claimed_a, 0)
        self.assertEqual(state_a.todo_rewards_claimed, 0)
        self.assertEqual(len(state_a.skipped), 1)
        claim_taps_a = [pt for name, pt in tapped_a if "TodoClaim" in name]
        self.assertEqual(claim_taps_a, [(1211, 102), (1211, 134)])
        self.assertTrue(any(ev["event"] == "unchanged_stop" for ev in diag_a.events))

        # 场景 B：点圆钮 (1211, 102) 成功触发弹窗及领取消失 -> 真实计入 1 次并干净停止
        tapped_b: list[tuple[str, tuple[int, int]]] = []
        done_b = {"claimed": False}

        def fake_tap_b(_ctx, name, pt):
            tapped_b.append((name, tuple(pt)))
            if "TodoClaim" in name:
                done_b["claimed"] = True
            return True

        def fake_ocr_claimed(_ctx, _img, node_name, _roi):
            if "TodoBtns" in node_name or "TodoChk" in node_name:
                return (
                    [{"text": "追踪", "center_x": 1211, "center_y": 134}]
                    if done_b["claimed"]
                    else [{"text": "领取", "center_x": 1211, "center_y": 134}]
                )
            if "TodoLvl" in node_name:
                return [{"text": "海岛等级：16"}]
            if "TodoTitles" in node_name:
                return [{"text": "其他任务" if done_b["claimed"] else "【海岛度假物语】将木屋升级到LV4"}]
            return []

        state_b = ipa._IslandExecState()
        with (
            patch.object(ipa, "safe_screencap", return_value=dummy_img),
            patch.object(ipa, "sleep_with_stop", return_value=True),
            patch.object(ipa, "is_stopping", return_value=False),
            patch.object(ipa, "_ensure_on_island_main", return_value=True),
            patch.object(ipa, "dismiss_reward_popup_if_present", return_value=True),
            patch.object(ipa, "tap_point", side_effect=fake_tap_b),
            patch.object(ipa, "ocr_roi", side_effect=fake_ocr_claimed),
        ):
            claimed_b = ipa._exec_claim_todo_rewards(None, "TodoOk", state_b)

        self.assertEqual(claimed_b, 1)
        self.assertEqual(state_b.todo_rewards_claimed, 1)
        claim_taps_b = [pt for name, pt in tapped_b if "TodoClaim" in name]
        self.assertEqual(claim_taps_b, [(1211, 102)])

        # 场景 C：点击领取后弹出「请用手指滑动屏幕」卡包奖励 -> 自动右划撕开、翻卡关结算后记 1 次领取
        self.assertTrue(is_island_card_pack_entries([{"text": "请用手指滑动屏幕"}]))
        self.assertFalse(is_island_card_pack_entries([{"text": "事项一览"}]))
        swipes_c: list[tuple[str, tuple[int, int], tuple[int, int]]] = []
        pack_stage = {"step": "todo_before"}  # todo_before -> pack -> reveal -> reward -> todo_after

        def fake_tap_c(_ctx, name, pt):
            if "TodoClaim" in name:
                pack_stage["step"] = "pack"
            elif "PackNext" in name:
                pack_stage["step"] = "reward"
            return True

        def fake_swipe_c(_ctx, name, start, end, **_kw):
            swipes_c.append((name, tuple(start), tuple(end)))
            pack_stage["step"] = "reveal"
            return True

        def fake_dismiss_c(_ctx, _prefix, _img=None, **_kw):
            if pack_stage["step"] == "reward":
                pack_stage["step"] = "todo_after"
            return True

        def fake_ocr_pack(_ctx, _img, node_name, _roi):
            st = pack_stage["step"]
            if "PackPrompt" in node_name:
                return [{"text": "请用手指滑动屏幕"}] if st == "pack" else []
            if "PackRT" in node_name:
                return [{"text": "获得物品"}] if st == "reward" else []
            if "PackRH" in node_name:
                return [{"text": "触碰空白区域退出"}] if st == "reward" else []
            if "TodoBtns" in node_name or "TodoChk" in node_name or "PackTodoB" in node_name:
                if st == "todo_before":
                    return [{"text": "领取", "center_x": 1211, "center_y": 134}]
                if st == "todo_after":
                    return [{"text": "追踪", "center_x": 1211, "center_y": 134}]
                return []
            if "TodoLvl" in node_name or "PackTodoL" in node_name:
                return [{"text": "海岛等级：16"}] if st in ("todo_before", "todo_after") else []
            if "TodoTitles" in node_name:
                return [{"text": "木屋LV4"}] if st == "todo_before" else ([{"text": "炒面摊"}] if st == "todo_after" else [])
            return []

        state_c = ipa._IslandExecState()
        diag_c = IslandDiagnosticRecorder(export_mode="log_only")
        with (
            patch.object(ipa, "safe_screencap", return_value=dummy_img),
            patch.object(ipa, "sleep_with_stop", return_value=True),
            patch.object(ipa, "is_stopping", return_value=False),
            patch.object(ipa, "_ensure_on_island_main", return_value=True),
            patch.object(ipa, "dismiss_reward_popup_if_present", side_effect=fake_dismiss_c),
            patch.object(ipa, "tap_point", side_effect=fake_tap_c),
            patch.object(ipa, "swipe_points", side_effect=fake_swipe_c),
            patch.object(ipa, "ocr_roi", side_effect=fake_ocr_pack),
        ):
            claimed_c = ipa._exec_claim_todo_rewards(None, "TodoPack", state_c, diag=diag_c)

        self.assertEqual(claimed_c, 1)
        self.assertEqual(state_c.todo_rewards_claimed, 1)
        self.assertEqual(swipes_c, [("TodoPackTodoPack0TearPack", (500, 182), (800, 182))])
        self.assertTrue(any(ev["stage"] == "card_pack" and ev["event"] == "opened" for ev in diag_c.events))


if __name__ == "__main__":
    unittest.main()
