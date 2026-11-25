"""Run reward regions independently without turning a failed region into success."""
from __future__ import annotations

import json

from maa.custom_action import CustomAction


REGIONS = (
    ('好友友情币', 'PrizeFriendCheck', ('好友友情币已检查',)),
    ('精彩活动', 'GetActivityPrizeMain', ('活动区域已扫描',)),
    ('任务奖励', 'GetTaskPrizeMain', ('任务区域已扫描', '日常任务无未完成项')),
    ('商城奖励', 'GetShoppingMallPrizeMain', ('商城区域已扫描',)),
    ('馈赠奖励', 'GetPresentMain', ('馈赠区域已扫描',)),
)


class PrizeRunner(CustomAction):
    @staticmethod
    def enabled(context, name):
        node = context.get_node_data(name)
        if not node:
            raise RuntimeError('无法读取领取开关：' + name)
        return node.get('enabled', True)

    @staticmethod
    def succeeded(result):
        return bool(result and result.status.succeeded)

    def verify(self, context, required, final=False):
        name = 'VerifyPrizeCompleted' if final else 'PrizeRegionCheckpointVerify'
        override = {name: {
            'recognition': 'DirectHit',
            'action': {'type': 'Custom', 'param': {
                'custom_action': 'verification_checkpoint',
                'custom_action_param': {
                    'task': '领取奖励', 'operation': 'verify',
                    'required': sorted(required),
                },
            }},
            'next': [],
        }}
        return self.succeeded(context.run_task(name, override))

    def run(self, context, argv):
        failures = []
        try:
            # Read the effective options before nested tasks install overrides.
            verify = context.get_node_data('VerifyPrizeCompleted')
            param = verify['action']['param']['custom_action_param']
            if isinstance(param, str):
                param = json.loads(param)
            required = set(param['required'])
            daily_enabled = self.enabled(context, 'DailyTaskPage')
            if not daily_enabled:
                required.discard('日常任务无未完成项')

            for label, entry, checkpoints in REGIONS:
                if context.tasker.stopping:
                    print('[领取奖励] 已停止，不再执行其他区域', flush=True)
                    return False
                enabled = self.enabled(context, entry)
                if entry == 'GetPresentMain':
                    enabled = enabled and self.enabled(context, 'EnterPresentPage')
                if not enabled:
                    required.difference_update(checkpoints)
                    print(f'[领取奖励] 按设置跳过：{label}', flush=True)
                    continue

                print(f'[领取奖励] 开始检查：{label}', flush=True)
                region_required = set(checkpoints)
                if not daily_enabled:
                    region_required.discard('日常任务无未完成项')
                try:
                    result = context.run_task(entry)
                    ok = self.succeeded(result)
                    if ok:
                        ok = self.verify(context, region_required)
                except Exception as error:
                    print(f'[领取奖励] {label}异常：{error}', flush=True)
                    ok = False
                if not ok:
                    failures.append(label)
                    print(f'[领取奖励] {label}未完成，记录失败后恢复页面', flush=True)
                else:
                    print(f'[领取奖励] 已复核：{label}', flush=True)

                # A failed subtask may leave any reward page/dialog open. Never
                # start the next region without positively recovering home.
                if context.tasker.stopping:
                    return False
                if not self.succeeded(context.run_task('PrizeRegionRecover')):
                    failures.append(label + '返回主界面')
                    print('[领取奖励] 无法确认主界面，停止后续区域以避免误点', flush=True)
                    break

            verified = self.verify(context, required, final=True)
            if failures:
                print('[领取奖励] 未完成区域：' + '、'.join(failures) + '；本次不能标记全部完成', flush=True)
            return verified and not failures
        except Exception as error:
            print(f'[领取奖励] 分区执行失败：{error}，未标记完成', flush=True)
            return False
