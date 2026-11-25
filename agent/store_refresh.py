"""Count a refresh only after the game's remaining counter decreases."""
import re
import time
from maa.custom_action import CustomAction
from collab_activity import ContextController, _capture


def remaining(detail):
    if not detail or not detail.hit:
        return None
    text = str(getattr(detail.best_result, 'text', '')).strip()
    return int(text) if re.fullmatch(r'10|[0-9]', text) else None


class StoreRefresh(CustomAction):
    def run(self, context, argv):
        controller = ContextController(context)
        def read():
            return remaining(context.run_recognition('GroceryRefreshCounter', _capture(controller)))
        try:
            before = read()
            if before is None or before <= 0:
                print('[商店刷新] 无法确认可刷新次数，停止', flush=True)
                return False
            # Exact centre of the visible “刷新” label, not the broad header.
            if not controller.post_click(545, 118).wait().succeeded:
                return False
            stable = 0
            for _ in range(10):
                time.sleep(0.5)
                after = read()
                stable = stable + 1 if after == before - 1 else 0
                if stable >= 2:
                    print(f'[商店刷新] 已确认剩余次数 {before} → {after}', flush=True)
                    return True
                if after is not None and after != before and after != before - 1:
                    break
            # Never click again after an ambiguous result: avoid extra purchases
            # or refreshes. A failed verification must fail the whole task.
            print('[商店刷新] 次数未确认减少，停止；不计为完成、不重复刷新', flush=True)
            return False
        except Exception as exc:
            print(f'[商店刷新] 复核失败：{exc}', flush=True)
            return False
