"""Queue-only MuMu startup recovery. Never changes VM data or Windows settings."""
import argparse
import json
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def queue_allows_start(text,instance,now):
    startup=None
    queue=None
    has_startup=False
    for line in text.splitlines():
        stamp=re.match(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)\]',line)
        if not stamp: continue
        when=datetime.fromisoformat(stamp.group(1))
        if 'MaaFramework 版本' in line:
            startup=when
            queue=None
            has_startup=False
        if f'/{instance}]' not in line: continue
        if '准备执行任务队列：任务数量=' in line:
            queue=when
            has_startup=False
        if queue and '任务管线合并' in line and '入口=[StartUp]' in line:
            has_startup=True
    return bool(queue and has_startup and (not startup or queue>=startup) and 0 <= (now-queue).total_seconds() <= 600)

def run(cli,args):
    result=subprocess.run([str(cli),*args],cwd=cli.parent,capture_output=True,
        text=True,encoding='utf-8',errors='replace',timeout=20,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode: raise RuntimeError(f'MuMu命令失败：{result.returncode} {result.stderr.strip()}')
    return json.loads(result.stdout)

def recover_stuck_backend(index):
    """Reset the stuck backend only when every running device is this instance."""
    script = r'''
$ErrorActionPreference = 'Stop'
$targetIndex = [int]$args[0]
$devices = @(Get-CimInstance Win32_Process -Filter "Name='MuMuNxDevice.exe'")
if ($devices.Count -eq 0) { throw '未找到可核对的 MuMu 实例，禁止重置共享后台' }
foreach ($device in $devices) {
    if (-not $device.CommandLine -or $device.CommandLine -notmatch '(?:^|\s)-v\s+(\d+)(?:\s|$)' -or [int]$Matches[1] -ne $targetIndex) {
        throw '存在无法确认或其他 MuMu 实例，禁止重置共享后台'
    }
}
$names = @('MuMuNxDevice.exe','MuMuNxMain.exe','MuMuNxService.exe','MuMuNxSVC.exe')
foreach ($proc in @(Get-CimInstance Win32_Process | Where-Object { $_.Name -in $names })) {
    Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
}
'''
    script = script.replace('$args[0]', str(int(index)))
    subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],
        capture_output=True,text=True,timeout=30,check=True,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))

def wait_ready(cli,adb,serial,index,seconds=480,emit=print):
    deadline=time.monotonic()+seconds
    launched=False
    recovered=False
    backend_reset=False
    post_reset_retry=False
    access_denied=False
    backend_wait_reported=False
    while time.monotonic()<deadline:
        try:
            info=run(cli,['info','-v',str(index)])
        except subprocess.TimeoutExpired:
            if not access_denied or backend_reset:
                raise
            emit('MuMu 管理器超时且已确认虚拟机访问被拒绝，检查是否可安全重置卡住的后台')
            recover_stuck_backend(index)
            backend_reset=True
            launched=False
            time.sleep(3)
            continue
        if info.get('is_android_started'):
            target=f"{info.get('adb_host_ip')}:{info.get('adb_port')}"
            if target!=serial: raise RuntimeError(f'实例端口与保存目标不一致：{target} != {serial}')
            subprocess.run([str(adb),'connect',serial],capture_output=True,timeout=10,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            boot=subprocess.run([str(adb),'-s',serial,'shell','getprop','sys.boot_completed'],capture_output=True,text=True,timeout=10,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if boot.returncode==0 and boot.stdout.strip()=='1':
                emit('安卓启动完成、ADB目标及开机状态均已确认')
                return True
        if not info.get('is_process_started') and not launched:
            emit(f'启动已配置的 MuMu 第 {index} 个实例')
            result=run(cli,['control','-v',str(index),'launch'])
            if result.get('errcode',0): raise RuntimeError(str(result))
            launched=True
        elif (backend_reset and not post_reset_retry and info.get('is_process_started')
              and info.get('vt_enabled') and info.get('launch_err_code',0)
              and 'VERR_NEM_VM_CREATE_FAILED' in str(info.get('launch_err_msg',''))):
            # The backend can be available but fail its first partition setup
            # after a reset. Retry this instance once; never loop or change VT.
            post_reset_retry=True
            emit('后台重置后虚拟化分区创建失败，延迟后仅重试当前实例一次')
            time.sleep(5)
            result=run(cli,['control','-v',str(index),'restart'])
            if result.get('errcode',0): raise RuntimeError(str(result))
            launched=True
        elif info.get('is_process_started') and info.get('launch_err_code',0) and not recovered and info.get('vt_enabled'):
            access_denied = 'VERR_VIRTUALBOX_ACCESSDENIED' in str(info.get('launch_err_msg',''))
            emit(f"启动失败：{info.get('launch_err_msg')}；仅恢复本实例一次")
            try:
                result=run(cli,['control','-v',str(index),'restart'])
            except subprocess.TimeoutExpired:
                if not access_denied or backend_reset: raise
                emit('实例重启超时，检查是否可安全重置卡住的后台')
                recover_stuck_backend(index)
                backend_reset=True
                result={'errcode':0}
                launched=False
                recovered=True
                time.sleep(3)
                continue
            if result.get('errcode',0): raise RuntimeError(str(result))
            recovered=True
            launched=True
        elif info.get('launch_err_code',0) and not backend_wait_reported:
            emit('等待虚拟化后端可用，再恢复失败实例；不反复重启或修改系统设置')
            backend_wait_reported=True
        time.sleep(5)
    emit('启动等待超时，未确认安卓就绪，不执行游戏任务')
    return False

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--instance',default='default')
    parser.add_argument('--from-mfa',action='store_true')
    args=parser.parse_args()
    instance=Path(args.instance).stem
    if instance!=args.instance: raise ValueError('配置名称非法')
    log=ROOT/'logs'/f'log-{datetime.now():%Y%m%d}.log'
    if args.from_mfa and (not log.is_file() or not queue_allows_start(
            log.read_text(encoding='utf-8', errors='replace'), instance, datetime.now())):
        print('没有当前执行队列的启动游戏授权；仅打开 MFA 时不启动模拟器',flush=True)
        return 0
    cfg=json.loads((ROOT/'config'/'instances'/f'{instance}.json').read_text(encoding='utf-8'))
    device=cfg['AdbDevice']
    if not all(device.get(key) for key in ('AdbPath', 'AdbSerial', 'Config')):
        print('请先打开 MuMu，在 MFA 搜索并选择设备，再开始任务。', flush=True)
        return 1
    extras=json.loads(device['Config'])['extras']['mumu']
    index=int(extras['index'])
    adb=Path(device['AdbPath'])
    cli=adb.parent/'MuMuManager.exe'
    if not cli.is_file(): cli=adb.parent/'mumu-cli.exe'
    (ROOT/'temp').mkdir(exist_ok=True)
    (ROOT/'logs').mkdir(exist_ok=True)
    import msvcrt
    with (ROOT/'temp'/f'mumu-recovery-{index}.lock').open('a+b') as lock:
        lock.seek(0)
        try: msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:
            print('已有本实例启动检查在进行，跳过重复启动',flush=True)
            return 0
        report=ROOT/'logs'/f'mumu-recovery-{datetime.now():%Y%m%d}.log'
        def emit(message):
            with report.open('a',encoding='utf-8') as output:
                output.write(f'[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}\n')
            print(message,flush=True)
        try:
            return 0 if wait_ready(cli,adb,device['AdbSerial'],index,emit=emit) else 1
        except Exception as error:
            emit(f'恢复失败：{error}')
            return 1
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)

if __name__=='__main__': raise SystemExit(main())
