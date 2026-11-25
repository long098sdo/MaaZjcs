"""Durable, fail-closed journal for per-pool daily draw limits.

The game account and reset cycle must be verified by the caller. This module
does not click, infer a reset time, or assign unexplained manual draws.
"""
import json
import os
import msvcrt
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from draw_quota_state import (QuotaState, begin_draw, confirm_draw,
                              start_verified_cycle, advance_verified_cycle, reconcile_manual, validate_state)


class QuotaJournal:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._locked = False

    @contextmanager
    def exclusive_run(self):
        """Hold this lock across reading, recording intent, click and commit."""
        if self._locked:
            raise ValueError('同一记录不可嵌套加锁')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_suffix(self.path.suffix + '.lock')
        with lock_path.open('a+b') as lock:
            lock.seek(0, os.SEEK_END)
            if not lock.tell():
                lock.write(b'0')
                lock.flush()
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise ValueError('已有同账号任务运行，禁止并发抽取') from exc
            try:
                self._locked = True
                yield self
            finally:
                self._locked = False
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)

    def read(self):
        try:
            raw = json.loads(self.path.read_text(encoding='utf-8'))
            if set(raw) != {'account', 'cycle', 'global_count', 'pool_counts', 'pending_pool'}:
                raise ValueError('记录字段不完整')
            state = QuotaState(**raw)
            validate_state(state)
            return state
        except (OSError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError('记录缺失或损坏，停止操作') from exc

    def _write(self, state):
        if not self._locked:
            raise ValueError('写入前必须持有排他锁')
        validate_state(state)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # The caller must hold an exclusive run lock across read, intent, click,
        # verification and commit. Never use a shared journal concurrently.
        staging = self.path.with_suffix(self.path.suffix + '.new')
        with staging.open('w', encoding='utf-8') as stream:
            json.dump(asdict(state), stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staging, self.path)

    def initialize(self, account, cycle, observed):
        if self.path.exists():
            raise ValueError('已有记录，不能覆盖')
        state = start_verified_cycle(account, cycle, observed)
        self._write(state)
        return state

    def begin(self, account, cycle, observed, pool, target):
        state = begin_draw(self.read(), account, cycle, observed, pool, target)
        self._write(state)
        return state

    def advance_cycle(self, account, cycle, observed):
        state = advance_verified_cycle(self.read(), account, cycle, observed)
        self._write(state)
        return state

    def reconcile_manual(self, account, cycle, observed, additions, allowed_pools):
        state = reconcile_manual(self.read(), account, cycle, observed, additions, allowed_pools)
        self._write(state)
        return state

    def confirm(self, observed):
        state = confirm_draw(self.read(), observed)
        self._write(state)
        return state
