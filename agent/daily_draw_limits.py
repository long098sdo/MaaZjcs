"""Strict parsing and safe limits for game-displayed daily draw counters."""
import re


def parse_daily_counter(text, activity):
    if activity not in ('结缘', '祈愿', '扭蛋'):
        raise ValueError('未知活动')
    compact = re.sub(r'\s+', '', str(text))
    # The game's OCR occasionally omits 日; keep both variants anchored.
    match = re.fullmatch(r'今(?:日)?已' + activity + r'(\d{1,5})[/／](\d{1,5})次', compact)
    if not match:
        raise ValueError('未能完整识别今日次数')
    done, cap = map(int, match.groups())
    if not 0 <= done <= cap <= 10000 or cap == 0:
        raise ValueError('今日次数超出范围')
    return done, cap


def safe_remaining(target, done, cap, balance, unit_cost):
    values = (target, done, cap, balance, unit_cost)
    if any(type(value) is not int for value in values):
        raise ValueError('次数或余额不是整数')
    if not (0 <= target <= 10000 and 0 <= done <= cap <= 10000 and cap > 0
            and balance >= 0 and unit_cost > 0):
        raise ValueError('次数或余额超出范围')
    return min(max(0, target - done), cap - done, balance // unit_cost)


def read_daily_counter(context, frame, node, activity):
    detail = context.run_recognition(node, frame)
    found = set()
    for item in (getattr(detail, 'all_results', []) if detail else []):
        try:
            found.add(parse_daily_counter(getattr(item, 'text', ''), activity))
        except ValueError:
            continue
    if len(found) != 1:
        raise ValueError('今日次数未能唯一确认，停止操作')
    return found.pop()


def read_player_number(context, frame):
    """Read a uniquely identified role number; never use a device ID as role ID."""
    detail = context.run_recognition('DrawPlayerNumber', frame)
    texts = [re.sub(r'\s+', '', str(getattr(item, 'text', '')))
             for item in (getattr(detail, 'all_results', []) if detail else [])]
    if sum('玩家编号' in text for text in texts) != 1:
        raise ValueError('玩家编号标签不明确')
    candidates = []
    for text in texts:
        match = re.fullmatch(r'(?:玩家编号[:：]?)?(\d{5,20})', text)
        if match:
            candidates.append(match.group(1))
    if len(set(candidates)) != 1:
        raise ValueError('玩家编号不明确')
    return candidates[0]


def parse_gacha_result_counter(text):
    compact = re.sub(r'\s+', '', str(text))
    match = re.fullmatch(r'今(?:日)?已开启(\d{1,5})[/／](\d{1,5})(?:次)?', compact)
    if not match:
        raise ValueError('未能完整识别扭蛋结果页今日次数')
    done, cap = map(int, match.groups())
    if not 0 <= done <= cap <= 10000 or not cap:
        raise ValueError('扭蛋结果页次数超出范围')
    return done, cap
