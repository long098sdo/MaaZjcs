"""Claim verified friendship-coin rewards available in the friends screen."""
import time
from datetime import datetime
from pathlib import Path

import cv2

from maa.custom_action import CustomAction
from collab_activity import ContextController, _capture, _click_box
from navigation_guard import locate


def save_evidence(frame, stage):
    """Keep the actual reward state for diagnosing scheduled claims."""
    try:
        ok, data = cv2.imencode('.png', frame)
        if ok:
            folder = Path(__file__).resolve().parents[1] / 'debug' / 'friend_rewards'
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f'{datetime.now():%Y%m%d-%H%M%S-%f}_{stage}.png'
            path.write_bytes(data.tobytes())
    except Exception:
        # Diagnostic storage must not change whether the reward was claimed.
        pass


class FriendRewards(CustomAction):
    def wait(self, context, controller, name, seconds=8):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            hit = locate(context, name, _capture(controller))
            if hit:
                return hit
            time.sleep(0.4)
        raise RuntimeError('未确认页面或按钮：' + name)

    def click(self, controller, hit):
        if not _click_box(controller, hit.box):
            raise RuntimeError('点击失败')
        time.sleep(0.8)

    def run(self, context, argv):
        controller = ContextController(context)
        try:
            self.wait(context, controller, 'GameAlreadyRunningMainTab')
            self.click(controller, self.wait(context, controller, 'FriendPrizeMenu'))
            self.click(controller, self.wait(context, controller, 'FriendPrizeMenuEntry'))
            self.wait(context, controller, 'FriendPrizePage')
            self.click(controller, self.wait(context, controller, 'FriendPrizeHeart'))
            self.wait(context, controller, 'FriendPrizePopup')
            frame = _capture(controller)
            save_evidence(frame, 'before')
            if not locate(context, 'FriendPrizeEmpty', frame):
                # Require a known friendship-reward source before claiming.
                if not locate(context, 'FriendPrizeBattleList', frame):
                    raise RuntimeError('既未识别空列表，也未识别可领取的好友奖励记录')
                claim = locate(context, 'FriendPrizeClaim', frame)
                if not claim:
                    raise RuntimeError('未确认友情币领取按钮')
                self.click(controller, claim)
                self.wait(context, controller, 'FriendPrizePopup')
                self.wait(context, controller, 'FriendPrizeEmpty')
                save_evidence(_capture(controller), 'claimed_empty')
                print('[好友奖励] 已领取友情币并确认列表清空', flush=True)
            else:
                print('[好友奖励] 已确认暂无可领取友情币', flush=True)
            if not controller.post_click(360, 1100).wait().succeeded:
                raise RuntimeError('关闭友情币窗口失败')
            time.sleep(0.8)
            self.wait(context, controller, 'FriendPrizePage')
            recovery = context.run_task('NavigationRecovery')
            if not recovery or not recovery.status.succeeded:
                raise RuntimeError('好友页面返回主界面失败')
            return True
        except Exception as error:
            print(f'[好友奖励] 失败：{error}，未标记完成', flush=True)
            return False
