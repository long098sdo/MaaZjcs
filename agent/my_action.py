import json
import re
import subprocess
import time
from pathlib import Path

from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction
from maa.context import Context
from guild_friendship import GuildFriendshipCollect
from store_refresh import StoreRefresh
from navigation_guard import NavigationGuard, StoreSearch, BoundedMapSwipe
from material_quick import MaterialQuickDig
from collab_activity import CollabBattleRunner, CollabPuzzleRunner, CollabPuzzleSolver, CollabEntryScan
AgentServer.register_custom_action('collab_entry_scan',CollabEntryScan())
from daily_activity import DailyActivityRunner
from spooky_rewards import SpookyRewards
from circuit_runner import CircuitRunner
from match3_runner import Match3Runner
from commission_safe import CommissionSafe
from draw_tree import DailyTreeDraw, FindTree
from draw_wish import WishRunner
from draw_gacha import CountryGachaRunner
AgentServer.register_custom_action('daily_tree_draw', DailyTreeDraw())
AgentServer.register_custom_action('find_tree_verified', FindTree())
AgentServer.register_custom_action('wish_runner', WishRunner())
AgentServer.register_custom_action('country_gacha_runner', CountryGachaRunner())
AgentServer.register_custom_action('commission_safe',CommissionSafe())
AgentServer.register_custom_action('match3_runner',Match3Runner())
AgentServer.register_custom_action('circuit_runner',CircuitRunner())
AgentServer.register_custom_action('spooky_free_rewards',SpookyRewards())
from energy_verified import EnergySelectAll, EnergyRecordPlan, EnergyVerifyConsumption, EnergyWaitConsumption
from friend_rewards import FriendRewards
AgentServer.register_custom_action('friend_rewards', FriendRewards())
from prize_runner import PrizeRunner
AgentServer.register_custom_action('prize_regions', PrizeRunner())
AgentServer.register_custom_action('energy_wait_consumption',EnergyWaitConsumption())
AgentServer.register_custom_action('energy_select_all_verified',EnergySelectAll())
AgentServer.register_custom_action('energy_record_plan',EnergyRecordPlan())
AgentServer.register_custom_action('energy_verify_consumption',EnergyVerifyConsumption())

AgentServer.register_custom_action('daily_activity_runner', DailyActivityRunner())

AgentServer.register_custom_action('guild_friendship_collect', GuildFriendshipCollect())
AgentServer.register_custom_action('store_refresh_verified', StoreRefresh())
AgentServer.register_custom_action('navigation_guard', NavigationGuard())
AgentServer.register_custom_action('store_search_bounded', StoreSearch())
AgentServer.register_custom_action('bounded_map_swipe', BoundedMapSwipe())
from navigation_guard import FeileNotFound, FeileLeftEdge
AgentServer.register_custom_action('feile_not_found', FeileNotFound())
AgentServer.register_custom_action('feile_left_edge', FeileLeftEdge())
AgentServer.register_custom_action('material_quick_dig', MaterialQuickDig())
AgentServer.register_custom_action('collab_puzzle_solver', CollabPuzzleSolver())
AgentServer.register_custom_action('collab_battle_runner', CollabBattleRunner())
AgentServer.register_custom_action('collab_puzzle_runner', CollabPuzzleRunner())


_verification_checkpoints: dict[str, set[str]] = {}
_guild_boss_remaining: dict[str, int] = {}


# Must match DailyTaskAllText's fixed OCR region in prize.json.  Text touching
# its edge may have been clipped even when OCR returns a plausible full label.
_DAILY_TASK_OCR_ROI = (10, 110, 700, 1050)


_DAILY_TASK_ENTRY_BY_TEXT = {
    "完成1次日常副本": "DailyDungeon",
    "今日上线登录": "StartUp",
    "家园商店购买2次": "Store",
    "消耗30点体力": "Energy",
    "探索5次素材秘境": "Material",
    "挑战1次幻想阶梯": "FantasyStairs",
    "参与1次公会讨伐": "Guild",
    "完成1次竞技场挑战": "Arena",
    "圣兽试炼领取1次": "BeastTrial",
    "双影幻境击破第3波": "DailyShadow",
}


def _enabled_task_entries() -> set[str] | None:
    """Read the currently checked task entries from MFA's active instance."""
    instance_path = Path(__file__).resolve().parents[1] / "config" / "instances" / "default.json"
    try:
        instance = json.loads(instance_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"[日常任务复核] 无法读取任务勾选状态：{error}")
        return None
    enabled = {
        str(item.get("entry", "")).strip()
        for item in instance.get("TaskItems", [])
        if item.get("default_check") and str(item.get("entry", "")).strip()
    }
    for item in instance.get("TaskItems", []):
        if item.get('entry') == 'Material':
            choices={option.get('name'):option for option in item.get('option',[])}
            materials=choices.get('素材多选',{}).get('selected_cases',['铁矿','金矿','精华','砂矿'])
            if not materials or all(choices.get(material+'使用方式',{}).get('index') == 2 for material in materials):
                enabled.discard('Material')
        if item.get('entry') == 'BeastTrial':
            if item.get('default_check') and not any(option.get('name')=='每日双影幻境' and option.get('index')==1 for option in item.get('option',[])):
                enabled.add('DailyShadow')
            for option in item.get('option',[]):
                if option.get('name') == '每日圣兽试炼' and option.get('index') == 1:
                    enabled.discard('BeastTrial')
        if item.get("entry") == "Guild":
            for option in item.get("option", []):
                if option.get("name") == "公会首领次数" and str(option.get("data", {}).get("首领次数", "")).strip() == "0":
                    enabled.discard("Guild")
    return enabled


def _daily_incomplete_selected_entries(results, enabled_entries: set[str]) -> tuple[list[str], list[str]]:
    """Match visible '前往' buttons to row labels and filter by checked tasks."""
    def center_y(box) -> float:
        if hasattr(box, "y"):
            return box.y + box.h / 2
        return box[1] + box[3] / 2

    text_results = [item for item in results if getattr(item, "text", "")]
    buttons = [item for item in text_results if re.match(r"^前往", str(item.text).strip())]
    selected: list[str] = []
    ignored: list[str] = []

    for button in buttons:
        button_y = center_y(button.box)
        candidates = []
        for item in text_results:
            text = re.sub(r"\s+", "", str(item.text))
            matched_label = next((label for label in _DAILY_TASK_ENTRY_BY_TEXT if label in text), None)
            if not matched_label:
                continue
            label_y = center_y(item.box)
            distance = button_y - label_y
            # A card's title is above its action; never borrow the next row's title.
            if 15 <= distance <= 110:
                candidates.append((distance, matched_label))

        if not candidates:
            ignored.append("未识别名称的日常项目")
            continue
        label = min(candidates)[1]
        entry = _DAILY_TASK_ENTRY_BY_TEXT[label]
        if entry in enabled_entries:
            selected.append(label)
        else:
            ignored.append(label)
    return selected, ignored


@AgentServer.custom_action("verification_checkpoint")
class VerificationCheckpoint(CustomAction):
    """Track and verify business-level task completion checkpoints."""

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> bool:
        try:
            param = json.loads(argv.custom_action_param or "{}")
        except json.JSONDecodeError:
            print("[任务复核] 无法读取检查点参数")
            return False

        task = str(param.get("task", "")).strip()
        operation = str(param.get("operation", "")).strip().lower()
        if not task:
            print("[任务复核] 缺少任务名称")
            return False

        if operation == "reset":
            _verification_checkpoints[task] = set()
            print(f"[任务复核] {task}：已开始记录关键步骤")
            return True

        if operation == "mark":
            checkpoint = str(param.get("checkpoint", "")).strip()
            if not checkpoint:
                print(f"[任务复核] {task}：缺少检查点名称")
                return False
            _verification_checkpoints.setdefault(task, set()).add(checkpoint)
            print(f"[任务复核] {task}：已确认 {checkpoint}")
            return True

        if operation == "verify":
            required = {
                str(item).strip()
                for item in param.get("required", [])
                if str(item).strip()
            }
            completed = _verification_checkpoints.get(task, set())
            missing = sorted(required - completed)
            if missing:
                print(f"[任务复核] {task}：未完成关键步骤：{', '.join(missing)}")
                return False
            print(f"[任务复核] {task}：本阶段复核通过（{', '.join(sorted(required))}）")
            # A jump-back node can legitimately reach the verifier more than once.
            # Keep successful checkpoints until the task entry explicitly resets them.
            return True

        print(f"[任务复核] {task}：未知操作 {operation}")
        return False


@AgentServer.custom_action("daily_task_selection_audit")
class DailyTaskSelectionAudit(CustomAction):
    """Only let checked MFA tasks block the daily-reward verification."""

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> bool:
        image_job = context.tasker.controller.post_screencap().wait()
        if not image_job.succeeded:
            print("[日常任务复核] 无法获取日常任务页面")
            return False

        detail = context.run_recognition("DailyTaskAllText", image_job.get())
        if detail is None:
            print("[日常任务复核] 无法启动文字识别")
            return False

        enabled_entries = _enabled_task_entries()
        if enabled_entries is None or not enabled_entries:
            print("[日常任务复核] 未获得任何已勾选任务，拒绝放行复核")
            return False
        selected, ignored = _daily_incomplete_selected_entries(detail.all_results, enabled_entries)
        if ignored:
            print(f"[日常任务复核] 未启用或次数设为0，保持不执行：{', '.join(dict.fromkeys(ignored))}")
        if selected:
            print(f"[日常任务复核] 已勾选但仍未完成：{', '.join(dict.fromkeys(selected))}")
            return False

        # The pipeline writes the completion checkpoint through the dedicated
        # verification action after this audit succeeds.  Keeping the audit and
        # checkpoint write as two explicit actions avoids losing the mark across
        # nested recognition calls.
        print("[日常任务复核] 已勾选任务均无可见的‘前往’项目，允许写入完成检查点")
        return True


@AgentServer.custom_action("beast_trial_daily_guard")
class BeastTrialDailyGuard(CustomAction):
    """Find the Beast Trial daily row regardless of the list's saved scroll position."""

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> bool:
        controller = context.tasker.controller

        # The daily list preserves its previous scroll position. Return to the top first.
        for _ in range(3):
            if not controller.post_swipe(360, 350, 360, 1000, 400).wait().succeeded:
                return False
            time.sleep(0.25)

        for page in range(4):
            image_job = controller.post_screencap().wait()
            if not image_job.succeeded:
                return False
            detail = context.run_recognition("DailyTaskAllText", image_job.get())
            if detail is None:
                return False
            results = [item for item in detail.all_results if getattr(item, "text", "")]
            def fully_inside_ocr_region(box):
                if hasattr(box, "x"):
                    x, y, width, height = box.x, box.y, box.w, box.h
                else:
                    x, y, width, height = box
                left, top, roi_width, roi_height = _DAILY_TASK_OCR_ROI
                return (width > 0 and height > 0 and x > left and y > top
                        and x + width < left + roi_width and y + height < top + roi_height)

            labels = [item for item in results
                      if "圣兽试炼领取1次" in re.sub(r"\s+", "", str(item.text))
                      and fully_inside_ocr_region(item.box)]
            for label in labels:
                label_box = label.box
                label_y = (label_box.y + label_box.h / 2) if hasattr(label_box, "y") else (label_box[1] + label_box[3] / 2)
                same_row = [
                    re.sub(r"\s+", "", str(item.text))
                    for item in results
                    if (
                        (item.box.x if hasattr(item.box, "x") else item.box[0]) >= 430
                        and fully_inside_ocr_region(item.box)
                        # Each card's action is below its title. A status from
                        # the previous card can be within 100 px above the
                        # title; accepting it could mark a truncated or missed
                        # current row as completed.
                        and 15 <= (
                            ((item.box.y + item.box.h / 2) if hasattr(item.box, "y") else (item.box[1] + item.box[3] / 2))
                            - label_y
                        ) <= 110
                    )
                ]
                if any(text.startswith("前往") for text in same_row):
                    print("[圣兽试炼复核] 日常任务仍显示‘前往’")
                    return False
                if any(text == "领取" or "已完成" in text for text in same_row):
                    _verification_checkpoints.setdefault("圣兽试炼", set()).add("日常任务已触发")
                    print("[圣兽试炼复核] 已确认‘圣兽试炼领取1次’完成")
                    return True
            if page < 3:
                if not controller.post_swipe(360, 1000, 360, 380, 450).wait().succeeded:
                    return False
                time.sleep(0.35)

        print("[圣兽试炼复核] 未找到‘圣兽试炼领取1次’项目")
        return False


@AgentServer.custom_action("guild_boss_remaining_guard")
class GuildBossRemainingGuard(CustomAction):
    """Record the visible guild-boss allowance and require it to decrease."""

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> bool:
        try:
            param = json.loads(argv.custom_action_param or "{}")
        except json.JSONDecodeError:
            param = {}

        operation = str(param.get("operation", "")).strip().lower()
        task = str(param.get("task", "公会")).strip() or "公会"

        if operation == "mark_participation_active":
            _verification_checkpoints.setdefault(task, set()).add("至少一次首领挑战已实际发起")
            print("[公会复核] 已确认加入正在进行的讨伐，不再等待首领结算")
            return True

        if operation == "verify_requested":
            try:
                requested = max(0, int(param.get("requested", 0)))
            except (TypeError, ValueError):
                print("[公会复核] 无法读取设置的首领挑战次数")
                return False
            checkpoints = _verification_checkpoints.setdefault(task, set())
            if requested == 0:
                checkpoints.add("首领挑战次数已核对")
                print("[公会复核] 首领挑战次数设置为 0，已按设置跳过")
                return True
            if "至少一次首领挑战已实际发起" not in checkpoints:
                print(f"[公会复核] 设置挑战 {requested} 次，但尚未确认实际发起")
                return False
            checkpoints.add("首领挑战次数已核对")
            print(f"[公会复核] 已确认按设置发起首领挑战（设置 {requested} 次）")
            return True

        image_job = context.tasker.controller.post_screencap().wait()
        if not image_job.succeeded:
            print("[公会复核] 无法获取讨伐次数截图")
            return False

        detail = context.run_recognition(
            "GuildBossRemainingOCR",
            image_job.get(),
        )
        text = ""
        if detail and detail.hit and detail.best_result is not None:
            text = str(getattr(detail.best_result, "text", ""))
        match = re.search(r"([0-2])\s*/\s*2", text)
        if not match:
            print(f"[公会复核] 未能读取今日剩余讨伐次数：{text or '无识别结果'}")
            return False

        current = int(match.group(1))
        if operation == "record":
            _guild_boss_remaining[task] = current
            print(f"[公会复核] 挑战前剩余次数：{current}/2")
            return True

        if operation == "verify_decreased":
            previous = _guild_boss_remaining.get(task)
            if previous is None:
                print("[公会复核] 缺少挑战前次数，拒绝判定成功")
                return False
            if current >= previous:
                print(f"[公会复核] 剩余次数未减少：{previous}/2 -> {current}/2")
                return False
            _guild_boss_remaining[task] = current
            _verification_checkpoints.setdefault(task, set()).add("至少一次首领挑战已实际发起")
            print(f"[公会复核] 已确认讨伐次数减少：{previous}/2 -> {current}/2")
            return True

        print(f"[公会复核] 未知操作：{operation}")
        return False


@AgentServer.custom_action("my_action_111")
class MyCustomAction(CustomAction):

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> bool:

        print("my_action_111 is running!")

        return True


@AgentServer.custom_action("redeem_codes")
class RedeemCodes(CustomAction):
    """Split a user supplied list and redeem every unique non-empty code."""

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> bool:
        try:
            param = json.loads(argv.custom_action_param or "{}")
        except json.JSONDecodeError:
            print("[兑换码] 无法读取兑换码列表")
            return False

        raw_codes = str(param.get("codes", ""))
        items = re.split(r"[\r\n,，;；]+", raw_codes)
        codes = list(dict.fromkeys(code.strip() for code in items if code.strip()))

        if not codes:
            print("[兑换码] 列表为空，跳过任务")
            return True

        completed = 0
        for index, code in enumerate(codes, start=1):
            print(f"[兑换码] 正在处理第 {index}/{len(codes)} 个：{code}")

            prepared = context.run_task("RedeemPrepare")
            if not prepared or not prepared.status.succeeded:
                print(f"[兑换码] 无法打开输入窗口，跳过：{code}")
                context.run_task("RedeemCleanup")
                continue

            submitted = context.run_task(
                "RedeemSubmit",
                pipeline_override={
                    "RedeemInputCode": {
                        "action": {
                            "param": {
                                "input_text": code,
                            }
                        }
                    }
                },
            )
            if submitted and submitted.status.succeeded:
                completed += 1
                print(f"[兑换码] 已提交：{code}")
            else:
                print(f"[兑换码] 提交失败，继续下一个：{code}")

            context.run_task("RedeemCleanup")

        print(f"[兑换码] 批量处理结束，共提交 {completed}/{len(codes)} 个")
        return completed == len(codes)


from mumu_shutdown import ShutdownMuMu
AgentServer.register_custom_action('shutdown_mumu', ShutdownMuMu())
