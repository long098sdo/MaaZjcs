"""Automation for the recurring collaboration-event battle and picture modes."""

from __future__ import annotations

import time
import traceback

import numpy as np
from maa.custom_action import CustomAction


class ContextController:
    """Reacquire IPC controller after each nested recognition call.

    AgentServer replaces borrowed controller proxies when context.tasker is read;
    retaining one across a recognition can leave a stale native pointer.
    """

    def __init__(self, context):
        self.context = context

    def __getattr__(self, name):
        return getattr(self.context.tasker.controller, name)


def _capture(controller):
    job = controller.post_screencap().wait()
    if not job.succeeded:
        raise RuntimeError("截图失败")
    return job.get()


def _groups(values: np.ndarray) -> list[int]:
    """Return centres of consecutive true runs."""
    result: list[int] = []
    start: int | None = None
    for index, value in enumerate(values.tolist() + [False]):
        if value and start is None:
            start = index
        elif not value and start is not None:
            result.append((start + index - 1) // 2)
            start = None
    return result


def _detect_grid(frame: np.ndarray) -> tuple[list[int], list[int]] | None:
    """Detect the full-height black grid lines of the picture puzzle."""
    gray = frame[:, :, :3].astype(np.float32).mean(axis=2)
    height, width = gray.shape
    if width < 650 or height < 1000:
        return None

    vertical_fraction = (gray[115:920, :] < 60).mean(axis=0)
    horizontal_fraction = (gray[:, 65:655] < 60).mean(axis=1)
    xs = [x for x in _groups(vertical_fraction > 0.55) if 65 <= x <= 655]
    ys = [y for y in _groups(horizontal_fraction > 0.55) if 100 <= y <= 940]

    # The three difficulties currently use increasingly dense rectangular grids.
    # Full-span line detection deliberately ignores character outlines and theme art.
    if not (3 <= len(xs) <= 7 and 3 <= len(ys) <= 9):
        return None
    x_steps = np.diff(xs)
    y_steps = np.diff(ys)
    if len(x_steps) == 0 or len(y_steps) == 0:
        return None
    if x_steps.max() - x_steps.min() > 6 or y_steps.max() - y_steps.min() > 6:
        return None
    return xs, ys


def _cell_patch(frame: np.ndarray, xs: list[int], ys: list[int], index: int) -> np.ndarray:
    columns = len(xs) - 1
    row, column = divmod(index, columns)
    margin = 8
    return frame[
        ys[row] + margin : ys[row + 1] - margin,
        xs[column] + margin : xs[column + 1] - margin,
        :3,
    ].astype(np.float32)


def _cell_center(xs: list[int], ys: list[int], index: int) -> tuple[int, int]:
    columns = len(xs) - 1
    row, column = divmod(index, columns)
    return (xs[column] + xs[column + 1]) // 2, (ys[row] + ys[row + 1]) // 2


def _remaining_bordered_cells(frame,xs,ys):
    """Require three full dark sides; locked art and outer borders are insufficient."""
    gray=frame[:,:,:3].astype(float).mean(axis=2)
    remaining=[]
    for index in range((len(xs)-1)*(len(ys)-1)):
        row,col=divmod(index,len(xs)-1)
        x0,x1,y0,y1=xs[col],xs[col+1],ys[row],ys[row+1]
        sides=[(gray[max(0,y0-2):y0+3,x0+8:x1-8]<40).mean(axis=1).max(),
               (gray[y1-2:y1+3,x0+8:x1-8]<40).mean(axis=1).max(),
               (gray[y0+8:y1-8,max(0,x0-2):x0+3]<40).mean(axis=0).max(),
               (gray[y0+8:y1-8,x1-2:x1+3]<40).mean(axis=0).max()]
        if sum(score>0.85 for score in sides)>=3:
            remaining.append(index)
    return remaining


def _locked_after_move(previous, current) -> bool:
    """Identify the game's uniform dimming of the exact moved piece, not dark art."""
    height = min(previous.shape[0], current.shape[0])
    width = min(previous.shape[1], current.shape[1])
    old = previous[:height, :width]
    new = current[:height, :width]
    ratio = float(new.mean() / max(1, old.mean()))
    return 0.2 < ratio < 0.72 and float(np.mean(np.abs(new - old * ratio))) < 18


def _has_movable_borders(frame) -> bool:
    """Even a partially locked grid retains black edges around movable cells."""
    gray = frame[:, :, :3].astype(np.float32).mean(axis=2)
    for columns, rows in ((2, 3), (3, 4), (4, 6)):
        xs = np.linspace(93, 626, columns + 1).round().astype(int)
        ys = np.linspace(133, 887, rows + 1).round().astype(int)
        for x in xs[1:-1]:
            for y0, y1 in zip(ys[:-1], ys[1:]):
                if (gray[y0 + 8:y1 - 8, x - 2:x + 3] < 100).mean(axis=0).max() > 0.85:
                    return True
        for y in ys[1:-1]:
            for x0, x1 in zip(xs[:-1], xs[1:]):
                if (gray[y - 2:y + 3, x0 + 8:x1 - 8] < 100).mean(axis=1).max() > 0.85:
                    return True
    return False


def _selected_cell(frame, xs, ys):
    for index in range((len(xs) - 1) * (len(ys) - 1)):
        row, column = divmod(index, len(xs) - 1)
        x0, x1, y0, y1 = xs[column], xs[column + 1], ys[row], ys[row + 1]
        edges = np.concatenate([
            frame[y0:y0 + 5, x0:x1, :3].reshape(-1, 3),
            frame[y1 - 5:y1, x0:x1, :3].reshape(-1, 3),
            frame[y0:y1, x0:x0 + 5, :3].reshape(-1, 3),
            frame[y0:y1, x1 - 5:x1, :3].reshape(-1, 3),
        ])
        yellow = (edges[:, 0] < 160) & (edges[:, 1] > 180) & (edges[:, 2] > 180)
        if yellow.mean() > 0.15:
            return index
    return None


def _cell_edges(frame, xs, ys, index):
    row, column = divmod(index,len(xs)-1)
    x0,x1,y0,y1=xs[column],xs[column+1],ys[row],ys[row+1]
    return np.concatenate([
        frame[y0:y0+5,x0:x1,:3].reshape(-1,3),
        frame[y1-5:y1,x0:x1,:3].reshape(-1,3),
        frame[y0:y1,x0:x0+5,:3].reshape(-1,3),
        frame[y0:y1,x1-5:x1,:3].reshape(-1,3),
    ]).astype(float)


def _click_box(controller, box) -> bool:
    return controller.post_click(box.x + box.w // 2, box.y + box.h // 2).wait().succeeded


def _wait_recognition(context, name: str, seconds: float, interval: float = 0.6):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        frame = _capture(context.tasker.controller)
        detail = context.run_recognition(name, frame)
        if detail and detail.hit:
            return detail
        time.sleep(interval)
    return None


def _puzzle_mode(frame):
    scores = []
    for x in (250, 435, 610):
        strip = frame[1240:1245, x - 10:x + 10, :3]
        scores.append(float(((strip[:, :, 0] < 150) & (strip[:, :, 1] > 140) & (strip[:, :, 2] > 140)).mean()))
    return int(np.argmax(scores)) if max(scores) > 0.4 else None


def _finish_puzzle(context, seconds: float = 12, mode=None) -> bool:
    """Wait through the final animation, dismiss rewards, then prove claimed."""
    controller = ContextController(context)
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        frame = _capture(controller)
        reward = context.run_recognition("CollabPuzzleReward", frame)
        if reward and reward.hit:
            if not _click_box(controller, reward.box):
                return False
            time.sleep(0.8)
            continue
        claimed = context.run_recognition("CollabPuzzleClaimed", frame)
        current_mode = _puzzle_mode(frame)
        if mode is not None and current_mode is not None:
            x = (294, 475, 656)[mode]
            previous = context.run_recognition("CollabPuzzleTabClaimed", frame, {
                "CollabPuzzleTabClaimed": {"recognition": {"param": {"roi": [x - 18, 1185, 36, 30]}}}
            })
            if previous and previous.hit:
                print("[联动拼图] 奖励已领取，已复核对应难度的勾选标记", flush=True)
                return True
        if claimed and claimed.hit and (mode is None or current_mode == mode):
            complete = context.run_recognition("CollabPuzzleComplete", frame)
            if complete and complete.hit:
                print("[联动拼图] 已确认本难度通关奖励领取，弹窗已关闭", flush=True)
                return True
        time.sleep(0.4)
    return False


def _scan_available(context, marker_name: str, page_name: str, content_name: str):
    """Sweep from top to bottom; a single viewport without red dots is not done."""
    controller = ContextController(context)
    if not _wait_recognition(context, page_name, 12):
        raise RuntimeError("未确认返回活动地图")
    # Reach the beginning regardless of the scroll position saved by the game.
    for _ in range(6):
        if not controller.post_swipe(360, 300, 360, 950, 350).wait().succeeded:
            raise RuntimeError("地图翻页失败")
        time.sleep(0.2)
    if not _wait_recognition(context, content_name, 15):
        raise RuntimeError("地图内容尚未加载，不能判定关卡已清空")
    stable = 0
    for page in range(16):
        frame = _capture(controller)
        detail = context.run_recognition(marker_name, frame)
        if detail and detail.hit:
            print(f"[联动扫描] 第 {page + 1} 屏发现可处理项目", flush=True)
            return detail
        if stable >= 2:
            # Recheck once after a loading grace period at the actual lower edge.
            time.sleep(1.2)
            frame = _capture(controller)
            detail = context.run_recognition(marker_name, frame)
            if detail and detail.hit:
                return detail
            print(f"[联动扫描] 已核对 {page + 1} 屏并到达底部，无剩余红点", flush=True)
            return None
        before = frame[150:1080:8, 40:680:8, :3].astype(float)
        if not controller.post_swipe(360, 950, 360, 300, 450).wait().succeeded:
            raise RuntimeError("地图翻页失败")
        time.sleep(1.0)
        after = _capture(controller)[150:1080:8, 40:680:8, :3].astype(float)
        stable = stable + 1 if float(np.mean(np.abs(before - after))) < 4 else 0
    raise RuntimeError("地图扫描达到上限，未确认清空，不标记完成")


class CollabEntryScan(CustomAction):
    """Distinguish no active collaboration from an unrecognized/broken page."""
    def run(self,context,argv):
        try:
            marker=_scan_available(context,'CollabEventBanner','CollabEventList','CollabEventList')
            if marker:
                detail=context.run_task('CollabOpenLinked')
                return bool(detail and detail.status.succeeded)
            print('[联动入口] 已完整扫描活动汇总，无联动入口，本期未开放/已结束，跳过；不是通关完成',flush=True)
            recovery=context.run_task('NavigationRecovery')
            return bool(recovery and recovery.status.succeeded)
        except Exception as error:
            print(f'[联动入口] 无法确认活动列表：{error}；不标记完成',flush=True)
            return False


class CollabPuzzleSolver(CustomAction):
    """Solve a picture by swaps only; never touches the item-completion button."""

    def run(self, context, argv) -> bool:
        controller = ContextController(context)
        try:
            initial = _capture(controller)
            mode = _puzzle_mode(initial)
            # Completed artwork can contain straight black outlines. The actual
            # claimed tick is stronger evidence than a guessed grid border.
            if _finish_puzzle(context, 0.5, mode=mode):
                return True
            reward = context.run_recognition("CollabPuzzleReward", initial)
            if reward and reward.hit:
                return _finish_puzzle(context, mode=mode)
            if mode in (0,1,2):
                columns,rows=((2,3),(3,4),(4,6))[mode]
                resume_xs=np.linspace(93,626,columns+1).round().astype(int).tolist()
                resume_ys=np.linspace(133,887,rows+1).round().astype(int).tolist()
                remaining=_remaining_bordered_cells(initial,resume_xs,resume_ys)
                if len(remaining)==2:
                    for cell in remaining:
                        if not controller.post_click(*_cell_center(resume_xs,resume_ys,cell)).wait().succeeded:
                            return False
                        time.sleep(0.8)
                    print('[联动拼图] 恢复未完成拼图，仅交换最后两块，不重置进度',flush=True)
                    return _finish_puzzle(context,mode=mode)
            if _detect_grid(initial) is None and not _has_movable_borders(initial):
                # This heading alone is never proof: it is also present while
                # playing. Only accept it when the movable grid has disappeared.
                complete = context.run_recognition("CollabPuzzleComplete", initial)
                if complete and complete.hit:
                    return _finish_puzzle(context, mode=mode)
            # Resetting costs nothing and guarantees that no previously locked cell
            # is mistaken for an ordinary dark image tile.  This button is separate
            # from the green double-arrow item-completion control, which is forbidden.
            # Orange circular-arrow reset at the top.  Its neighbour to the right
            # is the forbidden green item-completion button and is never touched.
            if not controller.post_click(400, 105).wait().succeeded:
                return False
            time.sleep(0.6)
            frame = _capture(controller)
            reset = context.run_recognition("CollabPuzzleResetDialog", frame)
            if reset and reset.hit:
                if not controller.post_click(505, 750).wait().succeeded:
                    return False
                time.sleep(0.9)

            frame = _capture(controller)
            grid = _detect_grid(frame)
            if grid is None:
                complete = context.run_recognition("CollabPuzzleComplete", frame)
                if complete and complete.hit and not _has_movable_borders(frame):
                    return _finish_puzzle(context, mode=mode)
                print("[联动拼图] 未检测到拼图网格，停止以避免误触", flush=True)
                return False
            xs, ys = grid
            cell_count = (len(xs) - 1) * (len(ys) - 1)
            print(
                f"[联动拼图] 检测到 {len(xs) - 1}×{len(ys) - 1} 网格，开始无道具还原",
                flush=True,
            )

            locked: set[int] = set()
            swaps = 0
            deadline = time.monotonic() + 600
            def finish_remaining():
                remaining=_remaining_bordered_cells(_capture(controller),xs,ys)
                if len(remaining)==2:
                    for cell in remaining:
                        if not controller.post_click(*_cell_center(xs,ys,cell)).wait().succeeded:
                            return False
                        time.sleep(0.8)
                    print('[联动拼图] 已交换最后两个完整黑边未锁定块，等待领奖复核',flush=True)
                return _finish_puzzle(context, mode=mode)
            # A reset produces a derangement.  For each destination, cycle every
            # still-movable tile through it.  The game darkens and locks the tile
            # immediately when it reaches its correct destination.
            for target in range(cell_count):
                # A correct tile briefly darkens, then returns to normal brightness
                # while remaining permanently immovable.  Therefore `locked` must
                # be cumulative: a fresh screenshot cannot rediscover old locks.
                if target in locked:
                    continue
                candidates = [
                    index
                    for index in range(cell_count)
                    if index != target and index not in locked
                ]
                # The shuffle may leave the destination's own tile in place without
                # locking it.  The first swap moves that tile to candidates[0]; visit
                # that cell once more after the cycle so the original tile can return
                # and trigger the game's lock.
                if candidates:
                    candidates.append(candidates[0])
                else:
                    # The game may lock the final piece automatically, then show
                    # its reward slightly later. Never fail before waiting for it.
                    return finish_remaining()
                found = False
                unchanged = 0
                # Verify immovability with an entire candidate cycle. Brightness
                # depends on the artwork and cannot reliably identify a lock.
                for source in candidates * 3:
                    if time.monotonic() >= deadline:
                        print("[联动拼图] 单个难度已达10分钟上限，停止并恢复主界面", flush=True)
                        return False
                    if source in locked:
                        continue
                    sx, sy = _cell_center(xs, ys, source)
                    tx, ty = _cell_center(xs, ys, target)
                    before = _capture(controller)
                    if not controller.post_click(sx, sy).wait().succeeded:
                        return False
                    time.sleep(0.3)
                    selected_frame = _capture(controller)
                    source_before_edges = _cell_edges(before,xs,ys,source)
                    source_selected_edges = _cell_edges(selected_frame,xs,ys,source)
                    selection_change = float(np.mean(np.abs(source_selected_edges-source_before_edges)))
                    if selection_change < 5 and _selected_cell(selected_frame,xs,ys) != source:
                        # A locked piece cannot be selected. Do not classify dark
                        # artwork as locked, and do not click another destination.
                        locked.add(source)
                        continue
                    if not controller.post_click(tx, ty).wait().succeeded:
                        return False
                    # A correct piece fades into the locked background after the
                    # swap animation.  Reading earlier can mistake it for movable.
                    time.sleep(0.75)
                    swaps += 1
                    after = _capture(controller)
                    source_after_edges = _cell_edges(after,xs,ys,source)
                    retained = (_selected_cell(after,xs,ys) == source or
                        float(np.mean(np.abs(source_after_edges-source_selected_edges))) < selection_change * 0.45)
                    if retained:
                        # Clicking a locked destination leaves its source selected.
                        # Cancel it before the next pair, or the next source click
                        # would swap with the leftover selection instead.
                        controller.post_click(sx, sy).wait()
                        time.sleep(0.15)
                        after = _capture(controller)
                    target_patch = _cell_patch(after, xs, ys, target)
                    after_source_patch = _cell_patch(after, xs, ys, source)

                    reward = context.run_recognition("CollabPuzzleReward", after)
                    if reward and reward.hit:
                        return _finish_puzzle(context, mode=mode)
                    if not _has_movable_borders(after):
                        if _finish_puzzle(context, 3, mode=mode):
                            return True
                    target_changed = float(np.mean(np.abs(target_patch - _cell_patch(before, xs, ys, target)))) > 3
                    source_changed = float(np.mean(np.abs(after_source_patch - _cell_patch(before, xs, ys, source)))) > 3
                    if retained and not target_changed:
                        locked.add(target)
                        found = True
                        print(f"[联动拼图] 移动后确认第 {target + 1}/{cell_count} 格锁定", flush=True)
                        break
                    if target_changed:
                        unchanged = 0
                    else:
                        unchanged += 1
                    if unchanged >= len(candidates):
                        locked.add(target)
                        found = True
                        print(
                            f"[联动拼图] 已锁定第 {target + 1}/{cell_count} 格",
                            flush=True,
                        )
                        break

                if not found:
                    if _finish_puzzle(context, mode=mode):
                        return True
                    print(
                        f"[联动拼图] 第 {target + 1} 格遍历后仍未锁定，停止避免无效点击",
                        flush=True,
                    )
                    return False

            return finish_remaining()
        except Exception as error:
            print(f"[联动拼图] 无道具解图失败：{error}", flush=True)
            return False


class CollabBattleRunner(CustomAction):
    """Clear every currently available stage in both difficulties."""

    def run(self, context, argv) -> bool:
        controller = ContextController(context)
        try:
            # Fixed mode layout is shared by each collaboration event; names change.
            if not controller.post_click(360, 930).wait().succeeded:
                return False
            if not _wait_recognition(context, "CollabBattleMap", 20):
                print("[联动战斗] 未进入战斗地图", flush=True)
                return False

            total = 0
            all_passed = True
            for label, tab_x in (("普通", 275), ("困难", 570)):
                controller.post_click(tab_x, 1215).wait()
                # Map contents load separately from the tabs.  Do not interpret
                # an empty loading background as no remaining stages.
                time.sleep(3.0)
                for _ in range(30):
                    marker = _scan_available(context, "CollabBattleAvailable", "CollabBattleMap", "CollabBattleContent")
                    if not marker or not marker.hit:
                        print(f"[联动战斗] {label}难度已无可挑战关卡", flush=True)
                        break

                    # The red exclamation bubble sits just above-right of the stage.
                    stage_x = max(25, min(695, marker.box.x + marker.box.w // 2 - 45))
                    stage_y = max(80, min(1040, marker.box.y + marker.box.h // 2 + 55))
                    controller.post_click(stage_x, stage_y).wait()
                    enter = _wait_recognition(context, "CollabBattleEnter", 6)
                    if not enter:
                        print(f"[联动战斗] {label}难度关卡入口未打开，任务失败", flush=True)
                        return False
                    if not _click_box(controller, enter.box):
                        return False
                    start = _wait_recognition(context, "CollabBattleStart", 8)
                    if not start:
                        print("[联动战斗] 未找到开始战斗按钮", flush=True)
                        return False
                    if not _click_box(controller, start.box):
                        return False

                    result = None
                    deadline = time.monotonic() + 180
                    while time.monotonic() < deadline:
                        shot = _capture(controller)
                        reward = context.run_recognition("CollabBattleReward", shot)
                        if reward and reward.hit:
                            _click_box(controller, reward.box)
                            result = "win"
                            break
                        failed = context.run_recognition("CollabBattleFailed", shot)
                        if failed and failed.hit:
                            result = "failed"
                            break
                        time.sleep(1.2)
                    if result is None:
                        print("[联动战斗] 3分钟内未识别到战斗结果", flush=True)
                        return False
                    if result == "failed":
                        controller.post_click(42, 1220).wait()
                        time.sleep(1.0)
                        print(f"[联动战斗] {label}难度当前关卡未通过，停止继续挑战", flush=True)
                        all_passed = False
                        break
                    total += 1
                    print(f"[联动战斗] 已完成第 {total} 个可挑战关卡", flush=True)
                    time.sleep(1.0)
                    # Reward closing normally returns to the map.  If it leaves us
                    # on a detail page, one bounded back press restores the map.
                    if not _wait_recognition(context, "CollabBattleMap", 5):
                        controller.post_click(42, 1220).wait()
                        if not _wait_recognition(context, "CollabBattleMap", 5):
                            return False
                else:
                    print("[联动战斗] 达到关卡上限，未确认清空", flush=True)
                    all_passed = False

            controller.post_click(42, 1220).wait()
            time.sleep(1.0)
            print(f"[联动战斗] 本次共完成 {total} 个关卡", flush=True)
            return all_passed
        except Exception as error:
            traceback.print_exc()
            print(f"[联动战斗] 执行失败：{error}", flush=True)
            return False


class CollabPuzzleRunner(CustomAction):
    """Solve every currently available picture without using completion items."""

    def run(self, context, argv) -> bool:
        controller = ContextController(context)
        try:
            if not controller.post_click(230, 1130).wait().succeeded:
                return False
            time.sleep(1.5)
            completed = 0
            for _ in range(12):
                marker = _scan_available(context, "CollabPuzzleAvailable", "CollabPuzzleList", "CollabPuzzleList")
                if not marker or not marker.hit:
                    controller.post_click(42, 1220).wait()
                    time.sleep(0.8)
                    print(f"[联动拼图] 已无新拼图，本次完成 {completed} 个难度", flush=True)
                    return True

                # The marker is at the card's upper-right; tap the card body.
                card_x = max(80, min(640, marker.box.x + marker.box.w // 2 - 95))
                card_y = max(120, min(1080, marker.box.y + marker.box.h // 2 + 115))
                controller.post_click(card_x, card_y).wait()
                time.sleep(1.2)
                for difficulty, tab_x in (("简单", 250), ("普通", 435), ("困难", 610)):
                    controller.post_click(tab_x, 1218).wait()
                    time.sleep(1.0)
                    print(f"[联动拼图] 核实并处理{difficulty}难度", flush=True)
                    if not CollabPuzzleSolver().run(context, argv):
                        context.run_action('NavigationRecovery')
                        return False
                    completed += 1
                controller.post_click(42, 1220).wait()
                time.sleep(1.0)

            print("[联动拼图] 达到安全处理上限，停止避免重复操作", flush=True)
            return False
        except Exception as error:
            print(f"[联动拼图] 执行失败：{error}", flush=True)
            context.run_action('NavigationRecovery')
            return False
