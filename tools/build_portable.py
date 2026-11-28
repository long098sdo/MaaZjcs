"""Build a clean Windows x64 distribution with local Python and .NET runtimes."""
import argparse
import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from hashlib import file_digest
from importlib.metadata import distribution
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT.parent / '发布包'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--version', required=True, help='Version written into the Windows release')
parser.add_argument('--official-mfa-archive', type=Path,
                    help='Use the official MFA v2.16.6 Windows x64 ZIP instead of local binaries')
parser.add_argument('--maafw-source', type=Path,
                    help='Official MaaFramework v5.14.3 source ZIP for the matching Python bindings')
args = parser.parse_args()
official_mfa = args.official_mfa_archive
maafw_source = args.maafw_source
if official_mfa:
    if not maafw_source:
        parser.error('Official MFA v2.16.6 requires the matching MaaFramework v5.14.3 source ZIP')
    with official_mfa.open('rb') as archive_file:
        digest = file_digest(archive_file, 'sha256').hexdigest()
    if digest != '01c5bd3747c50e1d302a69e4c5b728b956e4b3ede5eedfdb19afe546de072313':
        parser.error('MFA archive does not match the official v2.16.6 Windows x64 SHA-256')
stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
stage = OUTPUT / ('杖剑自动化-Windows64-' + stamp)
stage.mkdir(parents=True, exist_ok=False)

project_files = ('agent', 'resource', 'interface.json', 'README.md', 'CHANGELOG.md', 'LICENSE',
                 'THIRD-PARTY-NOTICES.md', 'tools/ensure_mumu_ready.py', 'tools/check_update.py',
                 'tools/UpdateTitleHook.cs',
                 '启动杖剑自动化.cmd', '检查更新.cmd')
local_runtime = ('libs', 'plugins', 'runtimes', 'MFAAvalonia.exe', 'MFAAvalonia.dll',
                 'MFAAvalonia.deps.json', 'MFAAvalonia.runtimeconfig.json', 'libloader.dll',
                 'DependencySetup_依赖库安装_win.bat')
if official_mfa:
    with zipfile.ZipFile(official_mfa) as bundle:
        bundle.extractall(stage)
for name in project_files if official_mfa else project_files + local_runtime:
    item = ROOT / name
    target = stage / name
    if item.is_dir():
        patterns = ['__pycache__', '*.pyc']
        if name == 'agent' and official_mfa:
            patterns.extend(('maa', 'maafw-*.dist-info'))
        shutil.copytree(item, target, ignore=shutil.ignore_patterns(*patterns))
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)

compiler = Path(os.environ['WINDIR']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
subprocess.run([str(compiler), '/nologo', '/target:library', '/codepage:65001',
                '/out:MaaZjcs.UpdateTitleHook.dll', 'UpdateTitleHook.cs'],
               cwd=stage / 'tools', check=True)

shutil.copytree(ROOT / 'android' / 'licenses' / 'project', stage / 'licenses')
if official_mfa:
    maa_package = stage / 'agent/vendor/maa'
    python_prefix = 'MaaFramework-5.14.3/source/binding/Python/maa/'
    with zipfile.ZipFile(maafw_source) as bindings:
        bindings.getinfo(python_prefix + '__init__.py')
        for name in bindings.namelist():
            if name.startswith(python_prefix) and name.endswith('.py'):
                relative = Path(name.removeprefix(python_prefix))
                if relative.is_absolute() or '..' in relative.parts:
                    raise ValueError('Invalid MaaFramework Python binding path')
                target = maa_package / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(bindings.read(name))
        (maa_package / 'LICENSE.md').write_bytes(bindings.read('MaaFramework-5.14.3/LICENSE.md'))
    shutil.copytree(stage / 'runtimes/win-x64/native', maa_package / 'bin')
    commit = '8646e0c34fa1fc52cd32505bc2020bae7da9d76a'
    (stage / 'MFA-SOURCE.md').write_text(
        '# MFAAvalonia v2.16.6\n\n'
        '本包使用未经修改的官方 Windows x64 发行文件。\n\n'
        f'- [对应源码（{commit}）](https://github.com/MaaXYZ/MFAAvalonia/tree/{commit})\n'
        '- [官方发行文件](https://github.com/MaaXYZ/MFAAvalonia/releases/tag/v2.16.6)\n'
        f'- 官方 Windows x64 ZIP 的 SHA-256：`{digest}`\n'
        '- [MaaFramework v5.14.3 Python 源码](https://github.com/MaaXYZ/MaaFramework/tree/v5.14.3/source/binding/Python/maa)。Python 端的 Windows DLL 取自同一个官方 MFA ZIP。\n'
        '- GPL-3.0 许可文本：`licenses/LICENSE-MFA-GPL-3.0`\n',
        encoding='utf-8')

opencv = distribution('opencv-python')
opencv_metadata = next(path.parts[0] for path in opencv.files if path.name == 'METADATA')
for path in ('cv2', opencv_metadata):
    shutil.copytree(opencv.locate_file(path), stage / 'agent' / 'vendor' / path,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))

python_home = Path(sys.executable).parent
python_target = stage / 'portable' / 'python'
python_target.mkdir(parents=True)
for name in ('python.exe', 'pythonw.exe', 'python311.dll', 'python3.dll',
             'vcruntime140.dll', 'vcruntime140_1.dll', 'LICENSE.txt'):
    shutil.copy2(python_home / name, python_target / name)
for name in ('Lib', 'DLLs'):
    shutil.copytree(python_home / name, python_target / name,
                    ignore=shutil.ignore_patterns('site-packages', '__pycache__', '*.pyc', 'test', 'tests'))
for name in ('tcl8.6', 'tcl8', 'tk8.6'):
    shutil.copytree(python_home / 'tcl' / name, python_target / 'tcl' / name,
                    ignore=shutil.ignore_patterns('demos'))

dotnet_home = Path(r'C:\Program Files\dotnet')
dotnet_target = stage / 'portable' / 'dotnet'
dotnet_target.mkdir(parents=True)
for name in ('dotnet.exe', 'LICENSE.txt', 'ThirdPartyNotices.txt'):
    shutil.copy2(dotnet_home / name, dotnet_target / name)
framework = json.loads((stage / 'MFAAvalonia.runtimeconfig.json').read_text(encoding='utf-8'))
required = tuple(map(int, framework['runtimeOptions']['framework']['version'].split('.')))
version = max((p.name for p in (dotnet_home / 'shared' / 'Microsoft.NETCore.App').iterdir()
               if p.is_dir() and tuple(map(int, p.name.split('.')[:2])) == required[:2]),
              key=lambda v: tuple(map(int, v.split('.'))))
shutil.copytree(dotnet_home / 'shared' / 'Microsoft.NETCore.App' / version,
                dotnet_target / 'shared' / 'Microsoft.NETCore.App' / version)
shutil.copytree(dotnet_home / 'host' / 'fxr' / version, dotnet_target / 'host' / 'fxr' / version)

interface = json.loads((stage / 'interface.json').read_text(encoding='utf-8'))
interface['agent']['child_exec'] = './portable/python/python.exe'
interface['version'] = args.version
interface.pop('github', None)
for task in interface['task']:
    task['default_check'] = False
pending_order = ['Adventure', 'Fruit', 'EnergyCircuit', 'CandyNight', 'Equipment', 'RedeemCode']
pending = {task['entry']: task for task in interface['task'] if task['entry'] in pending_order}
interface['task'] = ([task for task in interface['task'] if task['entry'] not in pending]
                     + [pending[entry] for entry in pending_order])
references = [interface['icon'], *interface.get('import', ()),
              *(path for resource in interface['resource'] for path in resource['path'])]
missing = [path for path in references if not (stage / path).exists()]
if missing:
    raise ValueError(f'Missing interface assets: {missing}')
(stage / 'interface.json').write_text(json.dumps(interface, ensure_ascii=False, indent=4), encoding='utf-8')

config_dir = stage / 'config' / 'instances'
config_dir.mkdir(parents=True)
instance = {
    'InstanceName': '默认配置', 'Resource': '官服', 'AdbDevice': {}, 'BeforeTask': 'None',
    'TaskItems': [{k: task[k] for k in ('name', 'label', 'entry', 'description', 'default_check') if k in task}
                  for task in interface['task']],
    'CurrentTasks': [],
}
(config_dir / 'default.json').write_text(json.dumps(instance, ensure_ascii=False, indent=2), encoding='utf-8')
(stage / 'config' / 'config.json').write_text(json.dumps({
    'CurrentLanguage': 'zh-CN', 'ColorTheme': 'Blue', 'BaseTheme': 'Light',
    'EnableCheckVersion': False, 'UI.HasCompletedFirstUseTutorial': False,
}, ensure_ascii=False, indent=2), encoding='utf-8')
(stage / 'appsettings.json').write_text(json.dumps({
    'Instances.List': 'default', 'Instances.Order': 'default',
    'Instances.LastActive': 'default', 'Instances.LastActiveName': '默认配置',
    'NoAutoStart': 'True', 'ForceScheduledStart': 'False',
    **{f'Timer.Timer{i}': 'False' for i in range(1, 9)},
}, ensure_ascii=False, indent=2), encoding='utf-8')

(stage / '使用说明.txt').write_text('''杖剑自动化便携版（Windows 64 位）

1. 将整个压缩包解压到可写的文件夹，不要在压缩包内直接运行。
2. 双击“启动杖剑自动化.cmd”。无需另外安装 Python 或 .NET。
3. 安装并打开 MuMu 模拟器，在模拟器内安装杖剑传说并登录自己的账号。
4. 在任务管理器上方选择模拟器，搜索设备并选择自己的 MuMu 设备，然后连接。
   若没有找到设备，检查 MuMu 的 ADB 调试是否开启，并重新搜索。
5. 先设置各项任务的次数和购买选项，再勾选需要运行的任务并点击开始。
6. 每次启动时后台检查更新。标题栏出现新版提示后，点击可在更新窗口直接下载。也可双击“检查更新.cmd”立即查询。

分发版所有任务默认未勾选，定时器、补跑和自动启动均已关闭。
联动拼图禁止使用道具。购买素材、商店购买、公会捐赠等应先检查配置。
需要定时运行时，请自行设置时间并开启定时器。
使用“启动游戏”自动开启模拟器时，请配置自己电脑上的 MuMu 路径和实例。
“结束任务”关闭所有 MuMu 实例和 MuMu 主程序，非默认安装位置需配置对应路径。

此包不包含模拟器、游戏和登录账号。此候选版仅列出官服资源。
请使用启动脚本启动，保留 portable、libs、agent、resource 等配套文件夹。
原项目许可证见 LICENSE，随附运行环境许可证位于 portable 下。
''', encoding='utf-8-sig')

# Verify the bundled interpreter can import every project action without global packages.
check = subprocess.run([str(python_target / 'python.exe'), '-I', '-B', '-c',
    "import sys; sys.dont_write_bytecode=True; sys.path[:0]=['agent/vendor','agent']; import my_action,my_reco; print('PORTABLE_AGENT_OK')"],
    cwd=stage, capture_output=True, text=True)
if check.returncode:
    raise RuntimeError(check.stdout + check.stderr)
print(check.stdout.strip())
runtime_check = subprocess.run([str(dotnet_target / 'dotnet.exe'), '--list-runtimes'],
                               capture_output=True, text=True, check=True)
print(runtime_check.stdout.strip())

archive = OUTPUT / (stage.name + '.zip')
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
    for file in stage.rglob('*'):
        if file.is_file() and '__pycache__' not in file.parts and file.suffix != '.pyc':
            bundle.write(file, str(Path(stage.name) / file.relative_to(stage)))
with zipfile.ZipFile(archive) as bundle:
    bad = bundle.testzip()
    if bad:
        raise RuntimeError('ZIP verification failed: ' + bad)
print('ARCHIVE=' + str(archive))
print('SIZE_MB=' + str(round(archive.stat().st_size / 1024 / 1024, 1)))
