"""Check MaaZjcs releases and offer a GitHub download on Windows."""

import argparse
import ctypes
import json
import re
import webbrowser
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'https://github.com/long098sdo/MaaZjcs'
RELEASES_API = 'https://api.github.com/repos/long098sdo/MaaZjcs/releases?per_page=100'
VERSION_PATTERN = re.compile(r'v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?')


def version_key(tag):
    match = VERSION_PATTERN.fullmatch(tag)
    if not match:
        raise ValueError(f'无法读取版本号 {tag}')
    major, minor, patch, prerelease = match.groups()
    identifiers = tuple((0, int(part)) if part.isdigit() else (1, part)
                        for part in prerelease.split('.')) if prerelease else ()
    return int(major), int(minor), int(patch), prerelease is None, identifiers


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
        asset_name = f'MaaZjcs-{tag}-win-x64.zip'.casefold()
        if any(asset.get('name', '').casefold() == asset_name and asset.get('state') == 'uploaded'
               for asset in release.get('assets', [])):
            candidates.append((key, tag))
    return max(candidates)[1] if candidates else None


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manual', action='store_true', help='Show status even when there is no update')
    parser.add_argument('--query', action='store_true', help='Print the latest eligible version without opening a dialog')
    parser.add_argument('--show-release', metavar='VERSION', help='Show the download prompt for a known release')
    args = parser.parse_args()
    try:
        current = json.loads((ROOT / 'interface.json').read_text(encoding='utf-8-sig'))['version']
        latest = args.show_release or find_update(current, read_releases())
        if latest:
            version_key(latest)
    except (OSError, ValueError, KeyError) as error:
        if args.manual:
            message(f'检查失败，请稍后重试。\n{error}', 0x30)
        return 1

    if args.query:
        if latest:
            print(latest)
        return 0
    if latest and message(f'发现新版本 {latest}（当前 {current}）。\n\n是否打开 GitHub 下载页？',
                          0x40 | 0x04 | 0x100) == 6:
        webbrowser.open(f'{REPOSITORY}/releases/tag/{latest}')
    elif not latest and args.manual:
        message(f'当前 {current}，GitHub 暂无符合当前版本渠道的新版 Windows 安装包。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
