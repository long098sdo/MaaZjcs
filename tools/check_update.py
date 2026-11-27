"""Check and download MaaZjcs releases on Windows."""

import argparse
import ctypes
import hashlib
import json
import os
import queue
import re
import tempfile
import threading
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'https://github.com/long098sdo/MaaZjcs'
RELEASES_API = 'https://api.github.com/repos/long098sdo/MaaZjcs/releases?per_page=100'
VERSION_PATTERN = re.compile(r'v?(\d+)\.(\d+)(?:\.(\d+))?(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?')


def version_key(tag):
    match = VERSION_PATTERN.fullmatch(tag)
    if not match:
        raise ValueError(f'无法读取版本号 {tag}')
    major, minor, patch, prerelease = match.groups()
    identifiers = tuple((0, int(part)) if part.isdigit() else (1, part)
                        for part in prerelease.split('.')) if prerelease else ()
    return int(major), int(minor), int(patch or 0), prerelease is None, identifiers


def find_update(current, releases):
    current_key = version_key(current)
    stable_only = current_key[3] or current.endswith('-local')
    candidates = []
    for release in releases:
        tag = release.get('tag_name', '')
        if release.get('draft') or not VERSION_PATTERN.fullmatch(tag):
            continue
        key = version_key(tag)
        if key <= current_key or (stable_only and (release.get('prerelease') or not key[3])):
            continue
        if release_asset(release):
            candidates.append((key, tag))
    return max(candidates)[1] if candidates else None


def release_asset(release):
    name = f'MaaZjcs-{release["tag_name"]}-win-x64.zip'.casefold()
    for asset in release.get('assets', []):
        if (asset.get('name', '').casefold() == name and asset.get('state') == 'uploaded'
                and isinstance(asset.get('size'), int) and asset['size'] > 0
                and re.fullmatch(r'sha256:[0-9a-f]{64}', asset.get('digest') or '', re.IGNORECASE)):
            return asset
    return None


def read_releases():
    request = Request(RELEASES_API, headers={'User-Agent': 'MaaZjcs-UpdateChecker',
                                             'Accept': 'application/vnd.github+json'})
    with urlopen(request, timeout=10) as response:
        releases = json.load(response)
    if not isinstance(releases, list):
        raise ValueError('GitHub 返回了无法识别的版本列表')
    return releases


def message(text, flags=0x40):
    return ctypes.windll.user32.MessageBoxW(None, text, 'MaaZjcs · 检查更新', flags | 0x10000)


class DownloadCancelled(Exception):
    pass


def download(tag, asset, directory, report_progress, cancelled):
    name = asset['name']
    if not VERSION_PATTERN.fullmatch(tag) or name.casefold() != f'MaaZjcs-{tag}-win-x64.zip'.casefold():
        raise ValueError('更新附件名不符合预期')
    size = asset['size']
    digest = hashlib.sha256()
    url = f'{REPOSITORY}/releases/download/{quote(tag, safe="")}/{quote(name, safe="")}'
    request = Request(url, headers={'User-Agent': 'MaaZjcs-UpdateChecker'})
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / name
    received = 0
    temporary = None
    try:
        with urlopen(request, timeout=20) as response, tempfile.NamedTemporaryFile(
                dir=directory, prefix=f'.{name}.', suffix='.part', delete=False) as out:
            temporary = Path(out.name)
            while not cancelled.is_set():
                block = response.read(256 * 1024)
                if not block:
                    break
                received += len(block)
                if received > size:
                    raise ValueError('下载大小超过发布记录')
                digest.update(block)
                out.write(block)
                report_progress(received, size)
        if cancelled.is_set():
            raise DownloadCancelled()
        if received != size or f'sha256:{digest.hexdigest()}' != asset['digest'].lower():
            raise ValueError('文件大小或 SHA-256 校验失败')
        os.replace(temporary, destination)
        return destination
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def show_update_window(current, latest, asset):
    import tkinter as tk
    from tkinter import ttk

    window = tk.Tk()
    window.title('MaaZjcs · 版本更新')
    window.resizable(False, False)
    window.columnconfigure(0, weight=1)
    content = ttk.Frame(window, padding=20)
    content.grid(sticky='ew')
    content.columnconfigure(0, weight=1)
    ttk.Label(content, text=f'发现新版本 {latest}', font=('Microsoft YaHei UI', 15, 'bold')).grid(sticky='w')
    ttk.Label(content, text=f'当前版本 {current}  ·  Windows x64  ·  {asset["size"] / 1048576:.1f} MB').grid(sticky='w', pady=(8, 14))
    progress = ttk.Progressbar(content, maximum=asset['size'], length=360)
    progress.grid(sticky='ew')
    status = tk.StringVar(value='下载后可从「更新下载」文件夹解压新版。')
    ttk.Label(content, textvariable=status, wraplength=360).grid(sticky='w', pady=(10, 16))
    actions = ttk.Frame(content)
    actions.grid(sticky='e')
    close_button = ttk.Button(actions, text='稍后')
    close_button.pack(side='right', padx=(8, 0))
    action_button = ttk.Button(actions, text='下载更新')
    action_button.pack(side='right')
    directory = ROOT / '更新下载'
    events = queue.SimpleQueue()
    cancelled = threading.Event()
    active = False

    def request_close():
        if active:
            cancelled.set()
            close_button.state(['disabled'])
            status.set('正在取消下载…')
        else:
            window.destroy()

    def worker():
        try:
            download(latest, asset, directory,
                     lambda read, total: events.put(('progress', (read, total))), cancelled)
            events.put(('done', None))
        except DownloadCancelled:
            events.put(('cancelled', None))
        except (OSError, ValueError) as error:
            events.put(('error', str(error)))

    def pump():
        nonlocal active
        while not events.empty():
            state, value = events.get_nowait()
            if state == 'progress':
                read, total = value
                progress['value'] = read
                if not cancelled.is_set():
                    status.set(f'正在下载  {read / 1048576:.1f} / {total / 1048576:.1f} MB  ·  {read / total:.0%}')
                continue
            active = False
            close_button.configure(text='关闭')
            close_button.state(['!disabled'])
            action_button.state(['!disabled'])
            if state == 'done':
                progress['value'] = asset['size']
                status.set('下载完成，SHA-256 校验通过。')
                action_button.configure(text='打开文件夹', command=lambda: os.startfile(directory))
            else:
                progress['value'] = 0
                status.set('已取消下载。' if state == 'cancelled' else f'下载失败：{value}')
                action_button.configure(text='重新下载', command=start_download)
            return
        if active:
            window.after(100, pump)

    def start_download():
        nonlocal active
        active = True
        cancelled.clear()
        close_button.configure(text='取消下载')
        action_button.state(['disabled'])
        status.set('正在连接下载源…')
        threading.Thread(target=worker, daemon=True).start()
        window.after(100, pump)

    close_button.configure(command=request_close)
    action_button.configure(command=start_download)
    window.protocol('WM_DELETE_WINDOW', request_close)
    window.mainloop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manual', action='store_true', help='Show status even when there is no update')
    parser.add_argument('--query', action='store_true', help='Print the latest eligible version without opening a dialog')
    parser.add_argument('--show-release', metavar='VERSION', help='Show the download window for a known release')
    args = parser.parse_args()
    try:
        current = json.loads((ROOT / 'interface.json').read_text(encoding='utf-8-sig'))['version']
        releases = read_releases()
        latest = find_update(current, releases if not args.show_release else
                             [r for r in releases if r.get('tag_name') == args.show_release])
    except (OSError, ValueError, KeyError) as error:
        if args.manual or args.show_release:
            message(f'检查失败，请稍后重试。\n{error}', 0x30)
        return 1

    if args.query:
        if latest:
            print(latest)
        return 0
    if latest:
        asset = next(release_asset(r) for r in releases if r['tag_name'] == latest and not r.get('draft'))
        show_update_window(current, latest, asset)
    elif args.manual or args.show_release:
        message(f'当前 {current}，GitHub 暂无符合当前版本渠道的新版 Windows 安装包。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
