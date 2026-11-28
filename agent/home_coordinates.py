"""Navigate the horizontally scrolling home scene without matching buildings."""
import time

import cv2
import numpy as np

from collab_activity import _capture

# World coordinates at the left boundary of the 720×1280 home scene.
DESTINATIONS = {
    '商店': (2328, 849, 'Groceries'),
    '命运之树': (1668, 748, 'PetWishPage'),
    '时光扭蛋机': (2150, 820, 'DrawGachaTodayCounter'),
}


def scene_displacement(before, after, swipe):
    """Measure foreground translation between two overlapping home screenshots."""
    expected = int(swipe * 1.85)
    tolerance = max(22, int(abs(expected) * .42))
    shifts = []
    for y in (805, 850, 885):
        for x in (240, 310, 380, 450, 520):
            left = max(18, x + expected - tolerance)
            right = min(680, x + expected + tolerance + 100)
            if right - left < 108:
                continue
            patch = before[y:y+46, x:x+100, :3]
            if patch.std() < 15:
                continue
            search = after[y-16:y+62, left:right, :3]
            _, score, _, (u, v) = cv2.minMaxLoc(cv2.matchTemplate(search, patch, cv2.TM_CCOEFF_NORMED))
            shift = left + u - x
            if score >= .82 and abs(v - 16) <= 13 and shift * swipe > 0:
                shifts.append(shift)
    if not shifts:
        return None
    groups = [[x for x in shifts if abs(x - shift) <= 5] for shift in shifts]
    best = max(groups, key=len)
    if len(best) < 3 or any(len(group) == len(best) and abs(np.median(group)-np.median(best)) > 5 for group in groups):
        return None
    return round(float(np.median(best)))


def recognized(context, node, frame):
    detail = context.run_recognition(node, frame)
    return detail if detail and detail.hit else None


def open_home_destination(context, controller, destination):
    """Return False when the coordinate route is unavailable on the home screen."""
    world_x, y, page = DESTINATIONS[destination]
    frame = _capture(controller)
    if not recognized(context, 'HomeCoordinatePage', frame):
        return False

    previous_x = None
    for _ in range(10):
        anchor = recognized(context, 'HomeCoordinateAnchor', frame)
        if anchor and 338 <= anchor.box.x <= 356:
            x = anchor.box.x
            if previous_x is not None and abs(x - previous_x) <= 3:
                break
            previous_x = x
        else:
            previous_x = None
        if not controller.post_swipe(220, 500, 480, 500, 350).wait().succeeded:
            return False
        time.sleep(.9)
        frame = _capture(controller)
        if not recognized(context, 'HomeCoordinatePage', frame):
            raise RuntimeError('回到家园左界时页面发生变化')
    else:
        print(f'[{destination}] 未确认飞艇位于家园左边界', flush=True)
        return False

    offset = 0
    for _ in range(16):
        x = world_x + offset
        if 145 <= x <= 555:
            if not controller.post_click(x, y).wait().succeeded:
                raise RuntimeError(f'{destination}入口点击失败')
            for _ in range(6):
                time.sleep(.55)
                frame = _capture(controller)
                if recognized(context, page, frame):
                    print(f'[{destination}] 坐标定位成功，位移{-offset}，点击({x},{y})，已复核页面', flush=True)
                    return True
            if not recognized(context, 'HomeCoordinatePage', frame):
                raise RuntimeError(f'{destination}坐标进入其他页面，停止操作')
            print(f'[{destination}] 坐标点击未打开目标页，改用原有入口识别', flush=True)
            return False
        if x < 145 or not controller.post_swipe(415, 500, 305, 500, 350).wait().succeeded:
            return False
        time.sleep(.8)
        following = _capture(controller)
        if not recognized(context, 'HomeCoordinatePage', following):
            raise RuntimeError('测量家园位移时页面发生变化')
        movement = scene_displacement(frame, following, -110)
        if movement is None:
            print(f'[{destination}] 家园位移无法确认，改用原有入口识别', flush=True)
            return False
        offset += movement
        frame = following
    return False
