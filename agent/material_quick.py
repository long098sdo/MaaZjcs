"""Enable and verify quick excavation before every material-consuming click."""
import time
from maa.custom_action import CustomAction
from collab_activity import ContextController, _capture


def hit(context, node, frame):
    detail = context.run_recognition(node, frame)
    return bool(detail and detail.hit)


def switch_state(frame):
    if frame is None or frame.shape[0] < 1065 or frame.shape[1] < 449:
        return None
    # Captures are BGR. Enabled: yellow knob on the right, dark text on
    # the left. Disabled: white knob on the left and a grey track on right.
    left = frame[1048:1065,381:398,:3].mean(axis=(0,1))
    right = frame[1048:1065,432:449,:3].mean(axis=(0,1))
    if right[1] > 150 and right[2] > 150 and right[0] < 140 and left.mean() < 110:
        return 'on'
    if left.mean() > 200 and left.max()-left.min() < 12 and 100 < right.mean() < 200 and right.max()-right.min() < 12:
        return 'off'
    return None


def ensure_quick(context, controller):
    frame = _capture(controller)
    if not hit(context, 'MaterialQuickLabel', frame):
        print('[快捷开凿] 未确认素材页面开关，停止开凿', flush=True)
        return False
    state = switch_state(frame)
    if state == 'on':
        return True
    if state != 'off':
        print('[快捷开凿] 无法识别开关状态，停止开凿', flush=True)
        return False
    if not controller.post_click(439,1056).wait().succeeded:
        return False
    for _ in range(4):
        time.sleep(0.4)
        frame = _capture(controller)
        if hit(context, 'MaterialQuickLabel', frame) and switch_state(frame) == 'on':
            print('[快捷开凿] 已开启并复核', flush=True)
            return True
    print('[快捷开凿] 点击后未确认开启，不消耗素材', flush=True)
    return False


class MaterialQuickDig(CustomAction):
    def run(self, context, argv):
        controller = ContextController(context)
        try:
            if not ensure_quick(context, controller):
                return False
            # Re-recognize the excavation button after the switch UI changed.
            frame = _capture(controller)
            detail = context.run_recognition(argv.node_name, frame)
            if not detail or not detail.hit:
                return False
            b = detail.box
            return controller.post_click(b.x+b.w//2,b.y+b.h//2).wait().succeeded
        except Exception as exc:
            print(f'[快捷开凿] 失败：{exc}', flush=True)
            return False
