"""Global crash guard for bonding; unresolved clicks require manual review."""
import json
import os
from contextlib import contextmanager
from pathlib import Path
from draw_quota_journal import QuotaJournal

ROOT = Path(__file__).resolve().parents[1]
MARKER = ROOT / 'config' / 'draw_safety' / 'tree-pending.json'


class TreeGuard:
    def __init__(self, marker=MARKER):
        self.marker = Path(marker)
        self._lock = QuotaJournal(self.marker.with_suffix('.guard'))

    @contextmanager
    def exclusive_run(self):
        with self._lock.exclusive_run():
            if self.marker.exists():
                raise ValueError('上次结缘结果未确认，请人工核对后处理待确认记录')
            yield self

    def begin(self, done, target):
        if not self._lock._locked:
            raise ValueError('未持有结缘排他锁')
        self.marker.parent.mkdir(parents=True, exist_ok=True)
        with self.marker.open('x', encoding='utf-8') as stream:
            json.dump({'before': done, 'target': target}, stream)
            stream.flush()
            os.fsync(stream.fileno())

    def confirm(self):
        if not self._lock._locked or not self.marker.is_file():
            raise ValueError('没有持锁的待确认结缘')
        self.marker.unlink()
