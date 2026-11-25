"""One journalled draw; page navigation and recognition are supplied separately."""
from draw_quota_state import validate_state


def execute_one(journal, account, cycle, pool, target, read_counter, click_once, wait_for_result):
    """Click at most once; failures after intent deliberately remain unresolved.

    `wait_for_result` must return only a freshly observed game total after the
    result page is safely dismissed. It must never make another draw.
    """
    with journal.exclusive_run():
        state = journal.read()
        validate_state(state)
        if state.account != account or state.cycle != cycle or state.pending_pool is not None:
            raise ValueError('账号、刷新周期或上次结果无法确认，停止')
        if type(target) is not int or not 0 <= target <= 10000 or not pool:
            raise ValueError('池子或目标次数无效')
        current = read_counter()
        if current != state.global_count:
            raise ValueError('游戏总次数有未归属变化，停止')
        if state.pool_counts.get(pool, 0) >= target:
            return False
        journal.begin(account, cycle, current, pool, target)
        if not click_once():
            raise RuntimeError('点击结果不确定，保留待核对记录，禁止重试')
        after = wait_for_result()
        journal.confirm(after)
        return True
