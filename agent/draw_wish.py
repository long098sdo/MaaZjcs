"""Verified per-pool wishing; unassignable manual draws stop the task."""
import hashlib
import json
import time
from datetime import datetime
from pathlib import Path

from maa.custom_action import CustomAction
from collab_activity import ContextController, _capture
from daily_draw_limits import read_daily_counter, read_player_number
from draw_feature_config import WISH, validate_targets, WISH_NODES, read_node_targets
from draw_quota_journal import QuotaJournal

ROOT = Path(__file__).resolve().parents[1]
POOLS = {
    '高阶祈愿': ('DrawWishAdvancedDescriptor', 'DrawWishAdvancedTab', 'DrawWishAdvancedBalance', 1),
    '常驻祈愿': ('DrawWishRegularDescriptor', 'DrawWishRegularTab', 'DrawWishRegularBalance', 1),
    '友情祈愿': ('DrawWishFriendDescriptor', 'DrawWishFriendTab', 'DrawWishFriendBalance', 25),
}


def hit(context, name, frame):
    result = context.run_recognition(name, frame)
    return result if result and result.hit else None


def click_box(controller, result):
    b = result.box
    if not controller.post_click(b.x + b.w // 2, b.y + b.h // 2).wait().succeeded:
        raise ValueError('点击未确认')


def number(context, name, frame):
    detail = context.run_recognition(name, frame)
    results = {int(x.text) for x in getattr(detail, 'all_results', []) if str(x.text).isdigit()} if detail else set()
    if len(results) != 1:
        raise ValueError('道具余额或单次费用未能唯一识别')
    return results.pop()


def role_key(context, controller):
    frame = _capture(controller)
    if not hit(context, 'GameAlreadyRunningMainTab', frame):
        raise ValueError('未确认家园，不能读取角色')
    if not controller.post_click(55, 55).wait().succeeded:
        raise ValueError('无法打开角色资料')
    time.sleep(1)
    player = read_player_number(context, _capture(controller))
    if not controller.post_click(360, 120).wait().succeeded:
        raise ValueError('无法关闭角色资料')
    time.sleep(1)
    if not hit(context, 'GameAlreadyRunningMainTab', _capture(controller)):
        raise ValueError('未确认已回到家园')
    return hashlib.sha256(player.encode()).hexdigest()


def open_wish(context, controller):
    for step in range(16):
        frame = _capture(controller)
        if not hit(context, 'GameAlreadyRunningMainTab', frame):
            raise ValueError('搜索雕像时离开家园')
        statue = hit(context, 'DrawAngelBuilding', frame)
        if statue:
            b = statue.box
            x, y = b.x + b.w // 2, b.y + b.h // 2 - 30
            if 70 <= x <= 620 and 400 <= y <= 900:
                if not controller.post_click(x, y).wait().succeeded:
                    raise ValueError('无法点击雕像')
                time.sleep(2)
                frame = _capture(controller)
                if any(hit(context, spec[0], frame) for spec in POOLS.values()):
                    return
                if not hit(context, 'GameAlreadyRunningMainTab', frame):
                    raise ValueError('雕像点击后进入未知页面')
        x1, x2 = (250, 500) if step < 8 else (500, 250)
        if not controller.post_swipe(x1, 500, x2, 500, 350).wait().succeeded:
            raise ValueError('家园滑动失败')
        time.sleep(.6)
    raise ValueError('未找到祈愿雕像')


class WishRunner(CustomAction):
    def run(self, context, argv):
        try:
            targets = read_node_targets(context, WISH_NODES) if hasattr(context, 'get_node_data') else validate_targets(json.loads(argv.custom_action_param or '{}'), WISH)
            if not any(targets.values()):
                print('[祈愿] 各池目标均为0，跳过', flush=True)
                return True
            controller = ContextController(context)
            if hit(context, 'DrawOtherClientLogin', _capture(controller)):
                raise ValueError('账号已在其他客户端登录，停止且不重新登录')
            navigation = context.run_task('NavigationRecovery')
            if not navigation or not navigation.status.succeeded:
                raise ValueError('无法确认主界面')
            account = role_key(context, controller)
            open_wish(context, controller)
            journal = QuotaJournal(ROOT / 'config/draw_safety' / ('wish-' + account + '.json'))
            with journal.exclusive_run():
                observed, _ = read_daily_counter(context, _capture(controller), 'DrawWishTodayCounter', '祈愿')
                if not journal.path.exists():
                    journal.initialize(account, datetime.now().isoformat(), observed)
                state = journal.read()
                if state.account != account or state.pending_pool:
                    raise ValueError('角色不匹配或上次祈愿结果未确认')
                previous_date = datetime.fromisoformat(state.cycle).date()
                current_date = datetime.now().date()
                if observed == 0 and (state.global_count > 0 or previous_date != current_date):
                    state = journal.advance_cycle(account, datetime.now().isoformat(), observed)
                elif previous_date != current_date:
                    raise ValueError('记录已跨日且今日次数不为零，无法确认各池手动次数')
                if observed != state.global_count:
                    raise ValueError('检测到无法归属的手动祈愿，请先核对各池次数')
                for pool in WISH:
                    if targets[pool] <= state.pool_counts.get(pool, 0):
                        continue
                    descriptor, tab, balance, unit = POOLS[pool]
                    frame = _capture(controller)
                    if not hit(context, descriptor, frame):
                        option = hit(context, tab, frame)
                        if option:
                            click_box(controller, option)
                        elif (pool == '高阶祈愿' and hit(context, 'DrawWishRegularDescriptor', frame)
                              and hit(context, 'DrawWishAdvancedPreview', frame)):
                            # The advanced card can be clipped at the left edge;
                            # only use its confirmed preview on the regular page.
                            if not controller.post_click(30, 1100).wait().succeeded:
                                raise ValueError('无法点击高阶祈愿卡片')
                        else:
                            raise ValueError(f'未找到{pool}页签')
                        time.sleep(1)
                        frame = _capture(controller)
                        if not hit(context, descriptor, frame):
                            raise ValueError(f'未确认选中{pool}')
                    while state.pool_counts.get(pool, 0) < targets[pool]:
                        frame = _capture(controller)
                        if not hit(context, descriptor, frame):
                            raise ValueError(f'{pool}页面未确认')
                        current, _ = read_daily_counter(context, frame, 'DrawWishTodayCounter', '祈愿')
                        if current != state.global_count:
                            raise ValueError('检测到无法归属的手动祈愿')
                        if number(context, 'DrawWishSingleCost', frame) != unit or number(context, balance, frame) < unit:
                            raise ValueError(f'{pool}道具余额或费用不足')
                        button = hit(context, 'DrawWishSingleButton', frame)
                        if not button:
                            raise ValueError(f'{pool}单次按钮未确认')
                        journal.begin(account, state.cycle, current, pool, targets[pool])
                        click_box(controller, button)
                        deadline = time.monotonic() + 25
                        result = None
                        while time.monotonic() < deadline:
                            time.sleep(1)
                            result_frame = _capture(controller)
                            try:
                                result, _ = read_daily_counter(context, result_frame, 'DrawWishResultCounter', '祈愿')
                                if result != current:
                                    break
                            except ValueError:
                                pass
                        if result != current + 1:
                            raise ValueError('抽取结果未确认，已保留待确认记录')
                        state = journal.confirm(result)
                        back = hit(context, 'LeaveCurrentPage', result_frame)
                        if not back:
                            raise ValueError('结果已记账，但返回按钮未识别')
                        click_box(controller, back)
                        time.sleep(1)
                        print(f'[祈愿] {pool}今日{state.pool_counts[pool]}/{targets[pool]}次', flush=True)
            return True
        except Exception as error:
            print(f'[祈愿] 停止：{error}', flush=True)
            return False
