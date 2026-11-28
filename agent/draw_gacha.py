"""Verified single-draw execution for the four country-ticket pools."""
import json
import re
import time
from datetime import datetime

from maa.custom_action import CustomAction
from collab_activity import ContextController, _capture
from daily_draw_limits import read_daily_counter, parse_gacha_result_counter
from draw_feature_config import validate_targets, COUNTRY_NODES, read_node_targets
from draw_quota_journal import QuotaJournal
from draw_wish import ROOT, hit, click_box, role_key
from home_coordinates import open_home_destination

COUNTRY = ('国度蓝券', '国度紫券', '国度橙券', '国度金券')
CARDS = {
    '国度蓝券': ('DrawGachaBlueSelected', 160),
    '国度紫券': ('DrawGachaPurpleSelected', 293),
    '国度橙券': ('DrawGachaOrangeSelected', 427),
    '国度金券': ('DrawGachaGoldSelected', 560),
}


def balance(context, frame):
    detail = context.run_recognition('DrawGachaTopBalance', frame)
    values = set()
    for item in (getattr(detail, 'all_results', []) if detail else []):
        # OCR sometimes reads a digit from the ticket icon next to the balance.
        if item.score < 0.8:
            continue
        match = re.fullmatch(r'(\d{1,5})\+?', str(getattr(item, 'text', '')).strip())
        if match: values.add(int(match.group(1)))
    if len(values) != 1:
        raise ValueError('扭蛋券余额未能唯一确认')
    return values.pop()


def verified_single_button(context, frame):
    button = hit(context, 'DrawGachaCompactSingleButton', frame)
    if button:
        cost_node = 'DrawGachaCompactSingleCost'
    else:
        button = hit(context, 'DrawGachaSingleButton', frame)
        cost_node = 'DrawGachaSingleCost'
    if not button:
        raise ValueError('扭蛋单次按钮未确认')
    if not hit(context, cost_node, frame):
        raise ValueError('未确认同一单次按钮的费用为10张券')
    return button


def result_counter(context, frame):
    detail = context.run_recognition('DrawGachaResultCounter', frame)
    values = set()
    for item in (getattr(detail, 'all_results', []) if detail else []):
        try: values.add(parse_gacha_result_counter(getattr(item, 'text', '')))
        except ValueError: pass
    if len(values) != 1:
        raise ValueError('扭蛋结果次数未能唯一确认')
    return values.pop()


def wait_result_return(context, controller, timeout=15):
    """Wait for the result animation; only click a recognized return button."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        frame = _capture(controller)
        if hit(context, 'DrawGachaTodayCounter', frame):
            return True
        back = hit(context, 'LeaveCurrentPage', frame)
        if back:
            click_box(controller, back)
            time.sleep(1)
            if hit(context, 'DrawGachaTodayCounter', _capture(controller)):
                return True
        time.sleep(1)
    return False


def open_gacha(context, controller):
    if open_home_destination(context, controller, '时光扭蛋机'):
        return
    for step in range(16):
        frame = _capture(controller)
        if not hit(context, 'GameAlreadyRunningMainTab', frame):
            raise ValueError('搜索扭蛋机时离开家园')
        machine = hit(context, 'DrawGachaBuilding', frame)
        if machine:
            b = machine.box
            x, y = b.x + b.w // 2, b.y
            if 70 <= x <= 620 and 400 <= y <= 900:
                if not controller.post_click(x, y).wait().succeeded:
                    raise ValueError('扭蛋机入口点击失败')
                time.sleep(2)
                frame = _capture(controller)
                if hit(context, 'DrawGachaTodayCounter', frame):
                    return
                if not hit(context, 'GameAlreadyRunningMainTab', frame):
                    raise ValueError('扭蛋机点击后进入未知页面')
        x1, x2 = (250, 500) if step < 8 else (500, 250)
        if not controller.post_swipe(x1, 500, x2, 500, 350).wait().succeeded:
            raise ValueError('家园滑动失败')
        time.sleep(.6)
    raise ValueError('未找到时光扭蛋机')


class CountryGachaRunner(CustomAction):
    def run(self, context, argv):
        try:
            targets = read_node_targets(context, COUNTRY_NODES) if hasattr(context, 'get_node_data') else validate_targets(json.loads(argv.custom_action_param or '{}'), COUNTRY)
            if not any(targets.values()):
                print('[时光扭蛋机] 国度各池目标均为0，跳过', flush=True)
                return True
            controller = ContextController(context)
            if hit(context, 'DrawOtherClientLogin', _capture(controller)):
                raise ValueError('账号已在其他客户端登录，停止且不重新登录')
            nav = context.run_task('NavigationRecovery')
            if not nav or not nav.status.succeeded: raise ValueError('无法确认主界面')
            account = role_key(context, controller)
            open_gacha(context, controller)
            journal = QuotaJournal(ROOT / 'config/draw_safety' / ('gacha-' + account + '.json'))
            with journal.exclusive_run():
                observed, _ = read_daily_counter(context, _capture(controller), 'DrawGachaTodayCounter', '扭蛋')
                if not journal.path.exists():
                    journal.initialize(account, datetime.now().isoformat(), observed)
                state = journal.read()
                if state.account != account or state.pending_pool: raise ValueError('账号不匹配或上次结果待确认')
                previous_date = datetime.fromisoformat(state.cycle).date()
                current_date = datetime.now().date()
                if observed == 0 and (state.global_count > 0 or previous_date != current_date):
                    state = journal.advance_cycle(account, datetime.now().isoformat(), observed)
                elif previous_date != current_date:
                    raise ValueError('记录已跨日且今日次数不为零，无法确认各池手动次数')
                if observed != state.global_count: raise ValueError('无法归属手动扭蛋次数，请先核对')
                for pool in COUNTRY:
                    if state.pool_counts.get(pool, 0) >= targets[pool]: continue
                    selected, x = CARDS[pool]
                    frame = _capture(controller)
                    if not hit(context, 'DrawGachaTodayCounter', frame): raise ValueError('未确认国度页面')
                    if not hit(context, selected, frame):
                        if not controller.post_click(x, 930).wait().succeeded: raise ValueError('券种切换失败')
                        time.sleep(1)
                        frame = _capture(controller)
                        if not hit(context, selected, frame): raise ValueError(f'未确认选中{pool}')
                    while state.pool_counts.get(pool, 0) < targets[pool]:
                        for attempt in range(3):
                            frame = _capture(controller)
                            if not hit(context, selected, frame): raise ValueError(f'{pool}选中状态不明')
                            current, _ = read_daily_counter(context, frame, 'DrawGachaTodayCounter', '扭蛋')
                            if current != state.global_count: raise ValueError('无法归属手动扭蛋')
                            try:
                                amount = balance(context, frame)
                                button = verified_single_button(context, frame)
                                break
                            except ValueError:
                                if attempt == 2: raise
                                time.sleep(1)
                        if amount < 10:
                            raise ValueError(f'{pool}余额{amount}张，单次需要10张')
                        journal.begin(account, state.cycle, current, pool, targets[pool])
                        click_box(controller, button)
                        deadline = time.monotonic() + 25
                        result = None
                        while time.monotonic() < deadline:
                            time.sleep(1)
                            result_frame = _capture(controller)
                            try:
                                result, _ = result_counter(context, result_frame)
                                if result != current: break
                            except ValueError: pass
                        if result != current + 1: raise ValueError('结果未确认，已保留待确认记录')
                        state = journal.confirm(result)
                        if not wait_result_return(context, controller):
                            raise ValueError('结果已记账，但结果页未能安全返回国度页面')
                        print(f'[时光扭蛋机] {pool}今日{state.pool_counts[pool]}/{targets[pool]}次', flush=True)
            return True
        except Exception as error:
            print(f'[时光扭蛋机] 停止：{error}', flush=True)
            return False
