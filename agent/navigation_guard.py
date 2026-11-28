"""Bounded recovery from exploration dialogs; never cancel a running hosting job."""
import time
import json
from maa.custom_action import CustomAction
from maa.custom_recognition import CustomRecognition
from collab_activity import ContextController, _capture
from home_coordinates import open_home_destination

_swipe_counts = {}
_feile_left_edges = set()


class FeileSearchTurn(CustomRecognition):
    def analyze(self, context, argv):
        count = _swipe_counts.get((argv.task_detail.task_id, 'left'), 0)
        if count >= 16:
            print('[找回奖励] 向左搜索16次仍未识别边界，切换方向继续搜索', flush=True)
            return (1, 1, 1, 1)
        return None


class FeileLeftEdge(CustomAction):
    def run(self, context, argv):
        _feile_left_edges.add(argv.task_detail.task_id)
        print('[找回奖励] 已确认左侧边界，开始搜索至右侧边界', flush=True)
        return True


class FeileNotFound(CustomAction):
    def run(self, context, argv):
        task_id = argv.task_detail.task_id
        if task_id not in _feile_left_edges:
            print('[找回奖励] 未确认左侧边界，无法确定是否存在可找回奖励', flush=True)
            return False
        _feile_left_edges.discard(task_id)
        print('[找回奖励] 已搜索家园两端，未发现菲乐；当前没有可找回奖励', flush=True)
        return True


class BoundedMapSwipe(CustomAction):
    def run(self, context, argv):
        direction = json.loads(argv.custom_action_param)['direction']
        key = (argv.task_detail.task_id, direction)
        count = _swipe_counts.get(key,0)
        if count >= 32:
            print(f'[搜索保护] {direction}已执行32次，停止任务，禁止无限循环',flush=True)
            return False
        _swipe_counts[key] = count+1
        coordinates = {'left':(250,500,500,500),'right':(500,500,250,500),
                       'up':(350,250,350,500),'down':(350,500,350,250)}
        job = ContextController(context).post_swipe(*coordinates[direction],350).wait()
        time.sleep(0.6)
        return job.succeeded


def locate(context, name, frame):
    detail = context.run_recognition(name, frame)
    return detail if detail and detail.hit else None


def click_box(controller, detail):
    b = detail.box
    return controller.post_click(b.x + b.w // 2, b.y + b.h // 2).wait().succeeded


class NavigationGuard(CustomAction):
    def run(self, context, argv):
        controller = ContextController(context)
        deadline = time.monotonic() + 300
        hosting_done = False
        story_clicks = 0
        gift_attempts = 0
        try:
            while time.monotonic() < deadline:
                frame = _capture(controller)
                # Require both a gift title and the offer's expiry/purchase
                # description before touching the known blank corner. Never
                # click the purchase button or dismiss an unknown dialog.
                if locate(context, 'CloseGift', frame) and locate(context, 'GiftPopupExpiry', frame):
                    gift_attempts += 1
                    if gift_attempts > 2:
                        print('[页面复核] 礼包弹窗未关闭，停止避免反复点击', flush=True)
                        return False
                    if not controller.post_click(50, 125).wait().succeeded:
                        return False
                    time.sleep(1)
                    print('[页面复核] 检测到限时礼包，点击弹窗外空白处', flush=True)
                    continue
                if locate(context,'CandySuccess',frame) and locate(context,'CandyReward',frame):
                    exit_button=locate(context,'CandySuccessExit',frame)
                    if not exit_button or not click_box(controller,exit_button):return False
                    time.sleep(1)
                    continue
                if locate(context,'CircuitSuccessTitle',frame):
                    exit_button=locate(context,'CircuitSuccessExit',frame)
                    if not exit_button or not click_box(controller,exit_button):return False
                    time.sleep(1)
                    continue
                if locate(context,'ShadowExitVote',frame):
                    if not controller.post_click(227,737).wait().succeeded:
                        return False
                    time.sleep(1)
                    continue
                if locate(context,'ShadowBattleWave',frame):
                    print('[页面复核] 双影幻境战斗仍在进行，等待结算，不发起退出投票',flush=True)
                    time.sleep(15)
                    continue
                if locate(context, 'CancelPuzzleDifficultyChange', frame):
                    if not controller.post_click(227,737).wait().succeeded:
                        return False
                    time.sleep(0.8)
                    continue
                if locate(context, 'ConfirmPuzzleExit', frame):
                    if not controller.post_click(493,737).wait().succeeded:
                        return False
                    time.sleep(0.8)
                    continue
                # A commission retry can start at the exploration confirmation.
                # Only cancel after recognizing both its text and Cancel button.
                if locate(context,'CommissionMapConfirm',frame):
                    cancel=locate(context,'CommissionMapCancel',frame)
                    if not cancel or not click_box(controller,cancel):return False
                    time.sleep(1)
                    if locate(context,'CommissionMapConfirm',_capture(controller)):
                        print('[页面复核] 探索确认框未关闭，停止恢复',flush=True)
                        return False
                    continue
                chat = locate(context, 'Chat', frame)
                if chat:
                    story_clicks += 1
                    if story_clicks > 60 or not click_box(controller, chat):
                        return False
                    time.sleep(0.8)
                    continue
                # Read the hosting dialog, but NEVER press its stop button.
                if locate(context, 'EndAutoPage', frame):
                    print('[页面复核] 托管仍在进行，继续等待，不取消托管', flush=True)
                    time.sleep(5)
                    continue
                # A failed commission can leave its *unstarted* hosting dialog
                # open.  Dismiss only after positively seeing its Start button;
                # then let the normal map-back recovery proceed.
                commission_ready=(locate(context,'CommissionHostTitle',frame) and locate(context,'CommissionHostStart',frame)) or (
                    locate(context,'CommissionCollectHostTitle',frame) and locate(context,'CommissionCollectStart',frame))
                if commission_ready:
                    if not controller.post_click(360,1120).wait().succeeded:return False
                    time.sleep(1)
                    new_frame=_capture(controller)
                    if locate(context,'CommissionHostTitle',new_frame) or locate(context,'CommissionCollectHostTitle',new_frame):
                        print('[页面复核] 委托托管面板未关闭，停止恢复',flush=True)
                        return False
                    hosting_done=True
                    continue
                if locate(context, 'StartAutoPage', frame):
                    hosting_done = True
                    if not controller.post_click(358, 1077).wait().succeeded:
                        return False
                    time.sleep(1)
                    continue
                auto = locate(context, 'AutoButton', frame)
                if auto and not hosting_done:
                    if not click_box(controller, auto):
                        return False
                    time.sleep(1)
                    continue
                if locate(context, 'GameAlreadyRunningMainTab', frame):
                    home = locate(context, 'HomePage', frame)
                    if home and not click_box(controller, home):
                        return False
                    time.sleep(1)
                    if locate(context, 'GameAlreadyRunningMainTab', _capture(controller)):
                        print('[页面复核] 已确认主界面可操作', flush=True)
                        return True
                leave = locate(context, 'LeaveCurrentPage', frame)
                if leave and (hosting_done or not auto):
                    if not click_box(controller, leave):
                        return False
                    time.sleep(1)
                    continue
                time.sleep(1)
            print('[页面复核] 超时，未确认托管结束或主界面，停止任务', flush=True)
            return False
        except Exception as exc:
            print(f'[页面复核] 失败：{exc}', flush=True)
            return False


class StoreSearch(CustomAction):
    def run(self, context, argv):
        controller = ContextController(context)
        try:
            if open_home_destination(context, controller, '商店'):
                return True
            for step in range(24):
                frame = _capture(controller)
                if not locate(context, 'GameAlreadyRunningMainTab', frame):
                    print('[商店搜索] 已离开主界面，停止滑动', flush=True)
                    return False
                store = locate(context, 'OpenStore', frame)
                if store:
                    for attempt in range(3):
                        if not click_box(controller, store):
                            return False
                        time.sleep(2)
                        opened = _capture(controller)
                        if locate(context,'Groceries',opened):
                            print(f'[商店搜索] 第 {step + 1} 屏进入杂货商店，已复核页面',flush=True)
                            return True
                        if not locate(context,'GameAlreadyRunningMainTab',opened):
                            print('[商店搜索] 点击后进入未知页面，停止避免误购',flush=True)
                            return False
                        store = locate(context,'OpenStore',opened)
                        if not store:
                            break
                    print('[商店搜索] 识别到建筑但未进入商店，继续有界搜索',flush=True)
                begin, end = (250, 500) if step < 12 else (500, 250)
                if not controller.post_swipe(begin, 500, end, 500, 350).wait().succeeded:
                    return False
                time.sleep(0.6)
            print('[商店搜索] 24 屏搜索上限到达，未找到商店，任务失败', flush=True)
            return False
        except Exception as exc:
            print(f'[商店搜索] 失败：{exc}', flush=True)
            return False
