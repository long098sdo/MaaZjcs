"""Halloween free rewards only: no purchases, paid tracks, exchanges or travel."""
import json
import re
import time
import numpy as np
from maa.custom_action import CustomAction
from collab_activity import ContextController, _capture, _click_box
from navigation_guard import locate

class SpookyRewards(CustomAction):
    def run(self,context,argv):
        self.context=context
        self.controller=ContextController(context)
        options=json.loads(argv.custom_action_param or '{}')
        try:
            if not self.wait('SpookyHub'): raise RuntimeError('未确认惊魂派对主页')
            if options.get('sign',True): self.sign()
            if options.get('manual',True): self.manual()
            print('[惊魂免费奖励] 已按开关完成复核；未操作付费/道具/前往入口',flush=True)
            return True
        except Exception as error:
            print(f'[惊魂免费奖励] 失败：{error}，未标记完成',flush=True)
            return False

    def wait(self,name,seconds=6):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            result=locate(self.context,name,_capture(self.controller))
            if result:return result
            time.sleep(0.4)
        return None

    def click(self,x,y):
        if not self.controller.post_click(x,y).wait().succeeded:raise RuntimeError('点击失败')
        time.sleep(0.7)

    def entry(self,name):
        result=self.wait(name)
        if not result:raise RuntimeError('入口不可见：'+name)
        if not _click_box(self.controller,result.box):raise RuntimeError('入口点击失败')
        time.sleep(1)

    def popup(self):
        for _ in range(8):
            frame=_capture(self.controller)
            if locate(self.context,'SpookyRewardPopup',frame):
                self.click(360,1120)
                return True
            time.sleep(0.3)
        return False

    def sign(self):
        self.entry('SpookySignEntry')
        if not self.wait('SpookySignPage'):raise RuntimeError('未确认惊奇日签')
        frame=_capture(self.controller)
        claim=locate(self.context,'SpookySignClaim',frame)
        if claim:
            if not _click_box(self.controller,claim.box):raise RuntimeError('日签点击失败')
            if not self.popup():raise RuntimeError('未见日签领奖弹窗')
            if not self.wait('SpookySignPage'):raise RuntimeError('领奖后未回日签')
            if locate(self.context,'SpookySignClaim',_capture(self.controller)):
                raise RuntimeError('日签仍显示领取')
            print('[惊奇日签] 已领取并复核按钮消失',flush=True)
        elif not locate(self.context,'SpookySignClaimed',frame):
            raise RuntimeError('没有已领取依据，不把无按钮当成功')
        else:print('[惊奇日签] 已有领取标记，跳过重复领取',flush=True)
        self.click(72,1220)
        if not self.wait('SpookyHub'):raise RuntimeError('日签返回失败')

    def manual(self):
        self.click(560,1218)
        self.entry('SpookyManualEntry')
        if not self.wait('SpookyManualPage'):raise RuntimeError('未确认怪谈手册')
        self.entry('SpookyManualTasksTab')
        stable=0
        claimed=0
        for page in range(14):
            if not self.wait('SpookyManualPage',2):raise RuntimeError('任务页意外变化')
            frame=_capture(self.controller)
            for _ in range(30):
                claim=locate(self.context,'SpookyManualTaskClaim',frame)
                if not claim:break
                before_progress=self.manual_progress(frame)
                if not _click_box(self.controller,claim.box):raise RuntimeError('任务领奖失败')
                popup=self.popup()
                after_progress=self.manual_progress(_capture(self.controller))
                if not popup and not after_progress>before_progress:raise RuntimeError('任务领奖后经验/等级未增长')
                claimed+=1
                frame=_capture(self.controller)
            else:raise RuntimeError('任务领奖超限')
            if stable>=2:break
            before=frame[420:1110:6,40:680:6,:3].astype(float)
            if not self.controller.post_swipe(350,1040,350,500,400).wait().succeeded:raise RuntimeError('任务列表滑动失败')
            time.sleep(0.8)
            after=_capture(self.controller)[420:1110:6,40:680:6,:3].astype(float)
            stable=stable+1 if np.abs(before-after).mean()<4 else 0
        else:raise RuntimeError('任务列表未确认到底')
        self.entry('SpookyManualRewardsTab')
        # Strictly restrict the search/click to the FREE left-hand reward column.
        # Never click level purchase, the right paid track or the unlock banner.
        for _ in range(5):
            self.controller.post_swipe(250,520,250,1000,300).wait()
            time.sleep(0.2)
        stable=0
        for page in range(20):
            if not self.wait('SpookyManualBasicHeading',2):raise RuntimeError('未确认基础奖励轨道')
            frame=_capture(self.controller)
            for _ in range(40):
                red=locate(self.context,'SpookyBasicRed',frame)
                if not red:break
                b=red.box
                if not (160<=b.x<335 and 450<=b.y<1025):raise RuntimeError('红点不在免费轨道')
                self.click(max(190,b.x-30),b.y+30)
                if not self.popup():raise RuntimeError('基础奖励没有领奖证据')
                claimed+=1
                frame=_capture(self.controller)
            else:raise RuntimeError('基础领奖超限')
            if stable>=2:break
            before=frame[460:1010:6,160:330:6,:3].astype(float)
            self.controller.post_swipe(250,950,250,520,400).wait()
            time.sleep(0.7)
            after=_capture(self.controller)[460:1010:6,160:330:6,:3].astype(float)
            stable=stable+1 if np.abs(before-after).mean()<4 else 0
        else:raise RuntimeError('基础奖励轨道未确认到底')
        self.click(360,1230)
        if not self.wait('SpookyHub'):raise RuntimeError('手册关闭失败')
        print(f'[怪谈手册] 免费任务/基础奖励复核完成，本轮领取{claimed}项',flush=True)

    def manual_progress(self,frame):
        detail=self.context.run_recognition('SpookyManualProgress',frame)
        text=' '.join(str(getattr(item,'text','')) for item in getattr(detail,'all_results',[]))
        ratio=re.search(r'(\d+)\s*[/／]\s*(\d+)',text)
        level=re.search(r'(\d+)\s*级',text)
        if not ratio:raise RuntimeError('手册经验无法读取')
        return (int(level.group(1)) if level else 0,int(ratio.group(1)))
