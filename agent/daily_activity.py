"""Independent daily activity execution, with bounded matching and reward proof."""
import json
import re
import time
from maa.custom_action import CustomAction
from collab_activity import ContextController, _capture, _click_box
from navigation_guard import NavigationGuard, locate

class DailyActivityRunner(CustomAction):
    def run(self, context, argv):
        options=json.loads(argv.custom_action_param or '{}')
        results=[]
        for label,enabled in (('圣兽试炼',options.get('beast',True)),('双影幻境',options.get('shadow',True))):
            if not enabled:
                print(f'[每日活动] {label}：按设置跳过',flush=True)
                continue
            if not (label=='双影幻境' and self.shadow_in_progress(context)) and not NavigationGuard().run(context,argv):
                results.append(False)
                continue
            try:
                if label=='圣兽试炼':
                    detail=context.run_task('BeastTrialOnly')
                    result=bool(detail and detail.status.succeeded)
                else:
                    result=self.shadow(context,argv)
            except Exception as error:
                print(f'[每日活动] {label}异常：{error}',flush=True)
                result=False
            results.append(result)
            print(f'[每日活动] {label}：{"完成" if result else "失败，未标记完成"}',flush=True)
            if not NavigationGuard().run(context,argv):
                results[-1]=False
        return all(results)

    def shadow_in_progress(self,context):
        frame=_capture(ContextController(context))
        return any(locate(context,name,frame) for name in ('ShadowBattleWave','ShadowExitVote','ShadowSummary'))

    def shadow(self,context,argv):
        controller=ContextController(context)
        def open_detail():
            detail=context.run_task('ShadowOpen')
            return bool(detail and detail.status.succeeded)
        resume=self.shadow_in_progress(context)
        if not resume and not open_detail():
            print('[双影幻境] 打开每日活动/双影详情失败，未标记完成',flush=True)
            return False
        frame=_capture(controller)
        reward=locate(context,'ShadowReward',frame)
        if not resume and not reward and self.already_claimed(context,frame):
            print('[双影幻境] 今日已有击破记录及已领取勾选标记，跳过重复匹配',flush=True)
            return True
        if not reward and not resume:
            match=locate(context,'ShadowMatch',frame)
            if not match or not _click_box(controller,match.box):
                print('[双影幻境] 未识别到匹配按钮或点击失败，未标记完成',flush=True)
                return False
            deadline=time.monotonic()+300
            ready=False
            started=False
            while time.monotonic()<deadline:
                frame=_capture(controller)
                if locate(context,'ShadowBattle',frame):
                    started=True
                    break
                accept=locate(context,'ShadowAccept',frame)
                if accept:
                    if not _click_box(controller,accept.box): return False
                    time.sleep(1)
                    continue
                if locate(context,'ShadowAlreadyReady',frame): ready=True
                if not ready:
                    button=locate(context,'ShadowReady',frame)
                    if button:
                        if not _click_box(controller,button.box): return False
                        ready=True
                time.sleep(1)
            if not started:
                print('[双影幻境] 匹配/准备5分钟内未进入战斗',flush=True)
                return False
            print('[双影幻境] 已进入战斗，等待3分钟；不重复点击准备',flush=True)
            time.sleep(180)
        if not reward:
            # Multiple waves can exceed the Beast Trial's three-minute duration.
            # Wait up to five more minutes, checking settlement only every 15s.
            deadline=time.monotonic()+300
            while time.monotonic()<deadline:
                frame=_capture(controller)
                if locate(context,'ShadowExitVote',frame):
                    if not controller.post_click(227,737).wait().succeeded: return False
                    time.sleep(1)
                    continue
                summary=locate(context,'ShadowSummary',frame)
                if summary:
                    action=context.run_action('ShadowSummary')
                    if not action or not action.success: return False
                    time.sleep(1)
                    continue
                if locate(context,'ShadowDetail',frame): break
                if locate(context,'GameAlreadyRunningMainTab',frame):
                    if not open_detail(): return False
                    break
                time.sleep(15)
            else:
                print('[双影幻境] 战斗后未回到活动界面',flush=True)
                return False
        return self.claim_shadow(context)

    def already_claimed(self,context,frame):
        progress=locate(context,'ShadowProgress',frame)
        text=str(getattr(getattr(progress,'best_result',None),'text',''))
        match=re.search(r'波次[:：]?([0-9]+)',re.sub(r'\s+','',text))
        return bool(match and int(match.group(1))>0 and locate(context,'ShadowClaimedTick',frame) and not locate(context,'ShadowReward',frame))

    def claim_shadow(self,context):
        controller=ContextController(context)
        # A red reward badge must be observed, clicked, and its popup closed.
        claimed=0
        popup_seen=False
        for _ in range(12):
            frame=_capture(controller)
            prize=locate(context,'ReceivePrize',frame)
            if prize:
                popup_seen=True
                if not _click_box(controller,prize.box): return False
                time.sleep(1)
                continue
            if not locate(context,'ShadowDetail',frame): return False
            reward=locate(context,'ShadowReward',frame)
            if not reward:
                if claimed and popup_seen:
                    print('[双影幻境] 已领取奖励，复核无剩余奖励红点',flush=True)
                    return True
                print('[双影幻境] 未取得领奖证据，未标记完成',flush=True)
                return False
            if not _click_box(controller,reward.box): return False
            claimed+=1
            time.sleep(1)
        return False
