"""Single-draw bonding with an authoritative in-game daily counter."""
import json
import re
import time
from maa.custom_action import CustomAction
from collab_activity import ContextController, _capture
from daily_draw_limits import read_daily_counter
from draw_tree_guard import TreeGuard


def read_balance(context, frame):
    detail = context.run_recognition('DrawTreeTokenBalance', frame)
    found = set()
    for item in (getattr(detail, 'all_results', []) if detail else []):
        text = re.sub(r'\s+', '', str(getattr(item, 'text', '')))
        if re.fullmatch(r'\d{1,6}', text):
            found.add(int(text))
    if len(found) != 1:
        raise ValueError('结缘道具余额未能唯一确认')
    return found.pop()


class DailyTreeDraw(CustomAction):
    def run(self, context, argv):
        try:
            raw = json.loads(argv.custom_action_param or '{}')
            target = raw.get('target', 0)
            if isinstance(target, str) and target.isascii() and target.isdigit() and len(target) <= 5:
                target = int(target)
            if type(target) is not int or not 0 <= target <= 10000:
                raise ValueError('结缘目标必须为0到10000的整数')
            with TreeGuard().exclusive_run() as guard:
                if target == 0:
                    print('[命运之树] 结缘目标为0，跳过结缘', flush=True)
                    return True
                return self._run_guarded(context, target, guard)
        except Exception as error:
            print(f'[命运之树] 停止：{error}', flush=True)
            return False

    def _run_guarded(self, context, target, guard):
            controller = ContextController(context)
            for _ in range(10000):
                frame = _capture(controller)
                done, cap = read_daily_counter(context, frame, 'DrawTreeTodayCounter', '结缘')
                if done >= target:
                    print(f'[命运之树] 今日已结缘{done}次，达到目标{target}次', flush=True)
                    return True
                if done >= cap or read_balance(context, frame) < 1:
                    raise ValueError(f'结缘绳不足或已达游戏上限，今日{done}/{target}次')
                button = context.run_recognition('DrawTreeSingleButton', frame)
                if not button or not button.hit:
                    raise ValueError('没有确认单次结缘按钮')
                box = button.box
                guard.begin(done, target)
                if not controller.post_click(box.x + box.w//2, box.y + box.h//2).wait().succeeded:
                    raise ValueError('点击结果不明确，停止')
                deadline = time.monotonic() + 20
                observed = None
                while time.monotonic() < deadline:
                    time.sleep(1)
                    try:
                        observed, new_cap = read_daily_counter(context, _capture(controller), 'DrawTreeTodayCounter', '结缘')
                        if observed != done:
                            break
                    except ValueError:
                        continue
                if observed != done + 1 or new_cap != cap:
                    raise ValueError(f'单次结缘后次数变化未确认：{done}→{observed}')
                guard.confirm()
                print(f'[命运之树] 已确认今日结缘{observed}/{target}次', flush=True)
            raise ValueError('达到安全循环上限')


class FindTree(CustomAction):
    def run(self, context, argv):
        controller = ContextController(context)
        try:
            adjustments = 0
            for step in range(48):
                frame = _capture(controller)
                home = context.run_recognition('GameAlreadyRunningMainTab', frame)
                if not home or not home.hit:
                    raise ValueError('未确认家园画面')
                tree = context.run_recognition('ClickTree', frame)
                # In the house a 250px gesture can move the scene by over
                # 450px, skipping the visible, unobstructed part of the tree.
                x1, x2 = (305, 415) if step < 16 else (415, 305)
                if tree and tree.hit:
                    box = tree.box
                    x = box.x + box.w // 2
                    y = box.y + box.h // 2 - 100
                    if 145 <= x <= 550 and 400 <= y <= 900:
                        if not controller.post_click(x, y).wait().succeeded:
                            raise ValueError('命运树入口点击未成功')
                        time.sleep(2)
                        page = context.run_recognition('PetWishPage', _capture(controller))
                        if page and page.hit:
                            print('[命运之树] 已确认进入结缘页面', flush=True)
                            return True
                        home = context.run_recognition('GameAlreadyRunningMainTab', _capture(controller))
                        if not home or not home.hit:
                            raise ValueError('入口点击后进入未知页面')
                    elif 400 <= y <= 900 and adjustments < 2:
                        # The template matches the base even when the clickable
                        # canopy is off to the side. Bring it into view first.
                        x1 = 360
                        x2 = 360 + max(-110, min(110, 360 - x))
                        adjustments += 1
                if not controller.post_swipe(x1, 500, x2, 500, 350).wait().succeeded:
                    raise ValueError('家园滑动失败')
                time.sleep(.6)
            raise ValueError('有界搜索未找到命运树')
        except Exception as error:
            print(f'[命运之树] 搜索失败：{error}', flush=True)
            return False
