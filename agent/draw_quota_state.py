"""Pure safety decisions for independently limited pools sharing a game counter.

The caller must persist an intent before clicking and the verified result after
the game counter advances. An unresolved intent is never automatically retried.
The account and game-reset cycle must be independently verified by the caller.
"""
from dataclasses import dataclass, replace
from datetime import datetime


@dataclass(frozen=True)
class QuotaState:
    account: str
    cycle: str
    global_count: int
    pool_counts: dict[str, int]
    pending_pool: str | None = None


def validate_state(state: QuotaState) -> None:
    if (not isinstance(state, QuotaState) or not isinstance(state.account, str) or not state.account
            or not isinstance(state.cycle, str) or not state.cycle
            or type(state.global_count) is not int or not 0 <= state.global_count <= 10000
            or not isinstance(state.pool_counts, dict)
            or any(not isinstance(key, str) or not key or type(value) is not int or value < 0
                   for key, value in state.pool_counts.items())
            or sum(state.pool_counts.values()) > state.global_count
            or (state.pending_pool is not None and
                (not isinstance(state.pending_pool, str) or not state.pending_pool))):
        raise ValueError('计数记录无效，停止执行')


def begin_draw(state: QuotaState, account: str, cycle: str, observed: int,
               pool: str, target: int) -> QuotaState:
    validate_state(state)
    if not account or account != state.account or not cycle or cycle != state.cycle:
        raise ValueError('账号或游戏刷新周期不一致')
    if state.pending_pool is not None:
        raise ValueError('上一次抽取结果未确认，禁止重试')
    if type(observed) is not int or observed != state.global_count:
        raise ValueError('游戏总次数有未归属的变化，停止而非猜测池子')
    if not isinstance(pool, str) or not pool or type(target) is not int or not 0 <= target <= 10000:
        raise ValueError('池子或目标次数无效')
    if state.pool_counts.get(pool, 0) >= target:
        raise ValueError('该池已达到设置次数')
    return replace(state, pending_pool=pool)


def confirm_draw(state: QuotaState, observed: int) -> QuotaState:
    validate_state(state)
    if state.pending_pool is None or type(observed) is not int or observed != state.global_count + 1:
        raise ValueError('未确认游戏次数恰好增加一次')
    counts = dict(state.pool_counts)
    counts[state.pending_pool] = counts.get(state.pending_pool, 0) + 1
    return replace(state, global_count=observed, pool_counts=counts, pending_pool=None)


def start_verified_cycle(account: str, cycle: str, observed: int) -> QuotaState:
    """A new cycle is usable only when a real game counter proves no draws.

    A nonzero first observation could include manual draws from any pool, so it
    cannot safely be assigned to the currently selected pool.
    """
    if (not isinstance(account, str) or not account or not isinstance(cycle, str) or not cycle
            or type(observed) is not int or observed != 0):
        raise ValueError('本周期已有无法归属的抽取次数，停止并请人工核对')
    return QuotaState(account, cycle, 0, {})


def advance_verified_cycle(state: QuotaState, account: str, cycle: str, observed: int) -> QuotaState:
    """Reset pool records only after the same role's game counter falls to zero."""
    validate_state(state)
    if state.pending_pool is not None:
        raise ValueError('仍有未确认的抽取，不能重置记录')
    if account != state.account or not cycle or cycle == state.cycle:
        raise ValueError('账号或新刷新周期无法确认')
    if type(observed) is not int or observed != 0:
        raise ValueError('未能证实游戏次数已刷新为零')
    if state.global_count == 0 and datetime.fromisoformat(state.cycle).date() == datetime.fromisoformat(cycle).date():
        raise ValueError('零次数记录未跨日，不能重复重置')
    return QuotaState(account, cycle, 0, {})


def reconcile_manual(state: QuotaState, account: str, cycle: str, observed: int,
                     additions: dict[str, int], allowed_pools: set[str]) -> QuotaState:
    """Accept an explicitly supplied per-pool breakdown only if totals agree."""
    validate_state(state)
    if state.pending_pool is not None or account != state.account or cycle != state.cycle:
        raise ValueError('账号、刷新周期或待确认抽取不允许手动核对')
    if type(observed) is not int or not state.global_count <= observed <= 10000:
        raise ValueError('游戏总次数无效')
    if (not isinstance(additions, dict) or not set(additions).issubset(allowed_pools)
            or any(type(value) is not int or value < 0 for value in additions.values())
            or sum(additions.values()) != observed - state.global_count):
        raise ValueError('分池手动次数与游戏总次数不一致')
    counts = dict(state.pool_counts)
    for pool, value in additions.items():
        counts[pool] = counts.get(pool, 0) + value
    result = replace(state, global_count=observed, pool_counts=counts)
    validate_state(result)
    return result
