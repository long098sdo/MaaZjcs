"""Collect only the observed water/clean help bubbles, with bounded verification."""
import json
import time
import numpy as np
from maa.custom_action import CustomAction
from collab_activity import ContextController


def _scroll_stopped(before, after):
    """Compare scene displacement, not leaf/chicken animation pixel changes."""
    a = before[140:948,30:690,:3].astype(float)
    b = after[140:948,30:690,:3].astype(float)
    if np.mean(np.abs(a-b)) < 4:
        return True
    # Phase correlation needs only NumPy, keeping the portable package intact.
    # Four-pixel blocks suppress local animation while preserving plot boundaries.
    a = a.mean(axis=2).reshape(202,4,165,4).mean(axis=(1,3))
    b = b.mean(axis=2).reshape(202,4,165,4).mean(axis=(1,3))
    a -= a.mean()
    b -= b.mean()
    spectrum = np.fft.fft2(a)*np.conj(np.fft.fft2(b))
    spectrum /= np.maximum(np.abs(spectrum),1e-9)
    correlation = np.fft.ifft2(spectrum).real
    y,x = np.unravel_index(np.argmax(correlation),correlation.shape)
    y = min(y,correlation.shape[0]-y)
    x = min(x,correlation.shape[1]-x)
    return bool(y <= 1 and x <= 1 and correlation.max() >= 0.15)


class GuildFriendshipCollect(CustomAction):
    def run(self, context, argv):
        area = json.loads(argv.custom_action_param)['area']
        if area not in ('田园', '鸡舍'):
            return False
        prefix = 'Farm' if area == '田园' else 'Hen'
        controller = ContextController(context)

        def capture():
            job = controller.post_screencap().wait()
            if not job.succeeded:
                raise RuntimeError('截图失败')
            frame = job.get()
            detail = context.run_recognition(prefix + 'FriendshipPage', frame)
            if not detail or not detail.hit:
                raise RuntimeError('已离开' + area + '页面')
            return frame

        def locate(frame):
            detail = context.run_recognition(prefix + 'FriendshipIcon', frame,
                {prefix + 'FriendshipIcon': {'recognition': {'param': {'roi': [20, 110, 680, 860]}}}})
            return detail.box if detail and detail.hit else None

        try:
            capture()
            def scroll_top():
                stable_top = 0
                for _ in range(12):
                    before = capture()
                    if not controller.post_swipe(350,300,350,870,350).wait().succeeded:
                        raise RuntimeError('返回田园/鸡舍顶部失败')
                    time.sleep(0.8)
                    after = capture()
                    stable_top = stable_top + 1 if _scroll_stopped(before,after) else 0
                    if stable_top >= 2:
                        return
                raise RuntimeError('未确认到达顶部，停止避免遗漏')
            # A fixed three swipes may cover only part of a large guild field.
            # Each verification sweep must start at the observed upper boundary.
            scroll_top()
            claimed = 0
            stable = 0
            sweep_start = 0
            sweeps = 0
            deadline = time.monotonic() + 180
            for page in range(72):
                if time.monotonic() >= deadline:
                    raise RuntimeError('三分钟复查上限到达，仍未确认清空')
                frame = capture()
                while True:
                    if time.monotonic() >= deadline:
                        raise RuntimeError('三分钟领取上限到达，仍未确认清空')
                    box = locate(frame)
                    if box is None:
                        break
                    if claimed >= 100:
                        raise RuntimeError('点击上限到达，仍存在待领图标')
                    x, y, w, h = box.x, box.y, box.w, box.h
                    if not controller.post_click(x + w // 2, y + h // 2).wait().succeeded:
                        return False
                    time.sleep(1.1)
                    after = capture()
                    # The same help bubble must disappear before moving to another one.
                    detail = context.run_recognition(prefix + 'FriendshipIcon', after,
                        {prefix + 'FriendshipIcon': {'recognition': {'param': {'roi': [x, y, w, h]}}}})
                    if detail and detail.hit:
                        raise RuntimeError('点击后友情币图标仍在，停止避免重复点击')
                    claimed += 1
                    print(f'[友情币] {area}：已确认第 {claimed} 个图标消失', flush=True)
                    frame = after
                before = frame
                if not controller.post_swipe(350, 880, 350, 330, 450).wait().succeeded:
                    return False
                time.sleep(0.8)
                after = capture()
                stable = stable + 1 if _scroll_stopped(before,after) and locate(after) is None else 0
                if stable >= 2:
                    sweeps += 1
                    if claimed == sweep_start:
                        print(f'[友情币] {area}：整页复查无剩余图标，共领取 {claimed} 次', flush=True)
                        return True
                    if sweeps >= 6:
                        raise RuntimeError('多轮复查仍有新增图标，本轮未确认清空')
                    sweep_start = claimed
                    stable = 0
                    scroll_top()
            raise RuntimeError('滚动检查上限到达，未确认到底')
        except Exception as exc:
            print(f'[友情币] {area}复核失败：{exc}', flush=True)
            return False
