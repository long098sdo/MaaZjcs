"""Gracefully close all MuMu instances and its main application."""
import csv
import io
import json
import subprocess
import time
from pathlib import Path

from maa.custom_action import CustomAction

ROOT = Path(__file__).resolve().parents[1]


def call_manager(cli, *args):
    result = subprocess.run([str(cli), *args], cwd=str(cli.parent), capture_output=True,
                            text=True, encoding='utf-8', errors='replace', timeout=30,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise RuntimeError(f"MuMu 命令失败（{result.returncode}）：{result.stderr.strip()}")
    if args and args[0] == 'info' and not result.stdout.strip():
        raise RuntimeError('MuMu 未返回实例状态')
    try:
        data = json.loads(result.stdout) if result.stdout.strip() else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError('MuMu 返回无法识别') from exc
    if not isinstance(data, dict) or data.get('errcode', 0) != 0:
        raise RuntimeError(f'MuMu 返回错误：{data}')
    return data


def running_instances(cli):
    info = call_manager(cli, 'info', '-v', 'all')
    for key, item in info.items():
        if (not str(key).isdigit() or not isinstance(item, dict)
                or not isinstance(item.get('is_process_started'), bool)
                or not isinstance(item.get('is_android_started'), bool)):
            raise RuntimeError('无法确认所有 MuMu 实例状态')
        if item.get('error_code', 0) != 0:
            raise RuntimeError(f'无法确认 MuMu 实例 {key} 状态')
    return [key for key, item in info.items()
            if item.get('is_process_started') or item.get('is_android_started')]


def main_is_running():
    result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq MuMuNxMain.exe', '/FO', 'CSV', '/NH'],
                            capture_output=True, text=True, timeout=15,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise RuntimeError('无法检查 MuMu 主程序状态')
    return any(row and row[0].strip().casefold() == 'mumunxmain.exe'
               for row in csv.reader(io.StringIO(result.stdout)))


def manager_path(param):
    configured = str(param.get('cli_path', '')).strip()
    candidates = [Path(configured)] if configured else []
    for name in ('default', 'caf68d6c'):
        try:
            config = json.loads((ROOT / 'config' / 'instances' / f'{name}.json').read_text(encoding='utf-8'))
            candidates.append(Path(config['AdbDevice']['AdbPath']).parent / 'MuMuManager.exe')
        except (OSError, ValueError, KeyError, TypeError):
            pass
    candidates += [Path(r'D:\Program Files\Netease\MuMuPlayer-12.0\MuMuPlayer\nx_main\MuMuManager.exe'),
                   Path(r'C:\Program Files\Netease\MuMuPlayer-12.0\MuMuPlayer\nx_main\MuMuManager.exe')]
    return next((path for path in candidates if path.is_file()), None)


def wait_until(predicate, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(1)
    return False


class ShutdownMuMu(CustomAction):
    def run(self, context, argv):
        try:
            param = json.loads(argv.custom_action_param or '{}')
            if not isinstance(param, dict):
                raise RuntimeError('关闭参数无效')
            cli = manager_path(param)
            if cli is None:
                raise RuntimeError('未找到 MuMuManager.exe')
            active = running_instances(cli)
            if active:
                print(f'[结束任务] 正在关闭所有 MuMu 实例：{", ".join(active)}', flush=True)
                call_manager(cli, 'control', '-v', 'all', 'shutdown')
                if not wait_until(lambda: not running_instances(cli)):
                    raise RuntimeError('等待 MuMu 实例关闭超时')
            if main_is_running():
                call_manager(cli, 'main', 'close')
                if not wait_until(lambda: not main_is_running(), timeout=20):
                    raise RuntimeError('MuMu 主程序未退出')
            if running_instances(cli) or main_is_running():
                raise RuntimeError('MuMu 仍有实例或主程序在运行')
            print('[结束任务] 已确认所有 MuMu 实例及主程序关闭', flush=True)
            return True
        except (OSError, ValueError, subprocess.SubprocessError, RuntimeError) as error:
            print(f'[结束任务] 关闭或复核失败：{error}', flush=True)
            return False
