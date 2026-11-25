"""Free-only commission submissions with per-operation counter verification."""
import re,time,json
import numpy as np
from types import SimpleNamespace
from maa.custom_action import CustomAction
from collab_activity import ContextController,_capture
from navigation_guard import locate
from energy_verified import read_ratio

def rect(box):
    return (box.x,box.y,box.w,box.h) if hasattr(box,'x') else tuple(box)

def count_from_text(value):
    matches=re.findall(r'(?<!\d)([0-4])\s*[/／]\s*4(?!\d)',value)
    if len(matches)!=1:raise RuntimeError('免费次数无法确认')
    return int(matches[0])

def read_commission_progress(ctx, frame, node):
    """Read progress even when OCR includes the nearby progress label."""
    detail=ctx.run_recognition(node,frame)
    pairs=[]
    for result in getattr(detail,'all_results',[]) if detail else []:
        value=re.sub(r'\s+','',str(getattr(result,'text','')))
        match=re.fullmatch(r'(?:(?:击杀数量|数量|量)[:：]?)?(\d{1,2})[/／](\d{1,2})',value)
        if match:pairs.append(tuple(map(int,match.groups())))
    if len(set(pairs))!=1:raise RuntimeError('委托进度无法唯一识别')
    return pairs[0]

def all_results(detail):
    return getattr(detail,'filtered_results',[]) if detail else []

def visual_bounty_banners(frame):
    """Detect the wide gold bounty banner even when OCR misses its text."""
    found=[]
    for x in (23,385):
        patch=frame[155:1110,x:x+125,:3].astype(np.int16)
        b,g,r=patch[:,:,0],patch[:,:,1],patch[:,:,2]
        gold=(r>165)&(g>110)&(r>b+35)&(g>b+20)
        rows=np.mean(gold,axis=1)>.55
        start=None
        for i,on in enumerate(list(rows)+[False]):
            if on and start is None:start=i
            elif not on and start is not None:
                if 10<=i-start<=35:found.append(SimpleNamespace(box=(x,155+start,125,i-start),text='重金悬赏'))
                start=None
    return found

def has_bounty_badge(title, badges):
    """A bounty banner sits immediately above its card title, not in artwork."""
    tx,ty,_,_=rect(title.box)
    # Real banners start about 37–41 px above their title.  The previous
    # row's yellow Submit button can be clipped at y=155 and sit ~64 px
    # above the next row's title; it must not be treated as a bounty.
    return any((rect(b.box)[0]<360)==(tx<360) and 20<=ty-rect(b.box)[1]<=55 for b in badges)

def bounty_badges(ctx, frame):
    text=all_results(ctx.run_recognition('CommissionBounty',frame))
    visual=visual_bounty_banners(frame)
    return [SimpleNamespace(box=b.box,text=getattr(b,'text',''),source='ocr') for b in text]+[
        SimpleNamespace(box=b.box,text=getattr(b,'text',''),source='visual') for b in visual]

def verify_bounty_consistency(titles, badges):
    """Never choose a normal card if OCR and the banner detector disagree."""
    for title in titles:
        text=has_bounty_badge(title,[b for b in badges if getattr(b,'source',None)=='ocr'])
        visual=has_bounty_badge(title,[b for b in badges if getattr(b,'source',None)=='visual'])
        if text!=visual:raise RuntimeError('重金标识识别不一致，停止以保留免费次数')

def clipped_previous_submit(badge, titles):
    """Reject a top-edge yellow strip belonging to the preceding card row."""
    bx,by,_,_=rect(badge.box)
    if getattr(badge,'source',None)!='visual' or by!=155:return False
    distances=[rect(t.box)[1]-by for t in titles
               if (rect(t.box)[0]<360)==(bx<360) and rect(t.box)[1]>by]
    return bool(distances and 55<min(distances)<=100)

def relocate_choice(choice, kind, titles, buttons, badges):
    """Re-identify the selected card after scrolling, never click saved pixels."""
    _,old_x,old_y,wanted=choice
    matches=[]
    for item in titles:
        tx,ty,tw,th=rect(item.box)
        if str(item.text)!=wanted or (tx<360)!=(old_x<360):continue
        for button in buttons:
            bx,by,bw,bh=rect(button.box)
            if (bx<360)!=(tx<360) or not 210<by-ty<350 or not 450<=by<=1110:continue
            x,y=bx+bw//2,by+bh//2
            if abs(y-old_y)>120:continue
            flagged=has_bounty_badge(item,badges)
            if flagged!=('重金' in kind):continue
            matches.append((x,y))
    if len(matches)!=1:raise RuntimeError('复位后无法唯一确认同一委托卡片，停止')
    return (kind,*matches[0],wanted)

def confirm_current_choice(kind, x, y, title, titles, buttons, badges):
    """Identify the same card on the current frame and click its current button.

    A list can still move after a scan.  A modest displacement is acceptable
    only when the card's column, title and bounty marker remain consistent;
    ambiguous matches must never be clicked.
    """
    matches=[]
    for button in buttons:
        bx,by,bw,bh=rect(button.box)
        cx,cy=bx+bw//2,by+bh//2
        if not 450<=by<=1110 or (bx<360)!=(x<360):continue
        if abs(cx-x)>60 or abs(cy-y)>80:continue
        matching_titles=[t for t in titles if str(t.text)==title
            and (rect(t.box)[0]<360)==(bx<360)
            and 210<by-rect(t.box)[1]<350]
        if len(matching_titles)!=1:continue
        if has_bounty_badge(matching_titles[0],badges)!=('重金' in kind):continue
        matches.append((cx,cy))
    if len(matches)!=1:raise RuntimeError('委托按钮或卡片发生变化，无法唯一确认')
    return matches[0]

class CommissionSafe(CustomAction):
    def after_submission(self,ctx,controller,before):
        """Wait for the counter; close only the observed affinity popup."""
        deadline=time.monotonic()+25
        while time.monotonic()<deadline:
            frame=_capture(controller)
            if locate(ctx,'CommissionAffinityPopup',frame) and locate(ctx,'CommissionClosePopupHint',frame):
                if not controller.post_click(360,1125).wait().succeeded:raise RuntimeError('关闭好感度提示失败')
                time.sleep(.8)
                continue
            if locate(ctx,'CommissionTitle',frame):
                try:after=self.counter(ctx,frame)
                except RuntimeError:time.sleep(.5);continue
                if after==before-1:return after
                if after!=before:raise RuntimeError('提交后免费次数变化异常')
            time.sleep(.5)
        raise RuntimeError('提交后未能确认免费次数，停止以免重复提交')

    def counter(self,ctx,frame):
        if not locate(ctx,'CommissionTitle',frame):raise RuntimeError('未确认委托页面或出现弹窗')
        result=ctx.run_recognition('CommissionCount',frame)
        return count_from_text(' '.join(str(getattr(r,'text','')) for r in all_results(result)))

    def scan(self,ctx,controller,test_title=None):
        # Inspect all pages before spending a free opportunity on ordinary work.
        for _ in range(5):
            if not controller.post_swipe(360,330,360,1030,350).wait().succeeded:
                raise RuntimeError('委托列表回顶滑动失败')
            time.sleep(.25)
        time.sleep(1.5)  # Wait for inertial scrolling before saving coordinates.
        stable=0; ordinary=None; bounty_pending=False; travel=None; bounty_travel=None
        for page in range(18):
            frame=_capture(controller);self.counter(ctx,frame)
            submit=all_results(ctx.run_recognition('CommissionSubmit',frame))
            badges=bounty_badges(ctx,frame)
            titles=all_results(ctx.run_recognition('CommissionCardTitle',frame))
            verify_bounty_consistency(titles,badges)
            forwards=all_results(ctx.run_recognition('CommissionForward',frame))
            for button in forwards:
                sx,sy,sw,sh=rect(button.box)
                if not 450<=sy<=1110:continue
                candidates=[t for t in titles if (rect(t.box)[0]<360)==(sx<360) and 210<sy-rect(t.box)[1]<350]
                if not candidates:continue
                title=str(candidates[0].text)
                if test_title and not title.startswith(test_title):continue
                flagged=has_bounty_badge(candidates[0],badges)
                if test_title:
                    return ('前往重金' if flagged else '前往普通',sx+sw//2,sy+sh//2,title)
                if flagged and bounty_travel is None:bounty_travel=(page,sx+sw//2,sy+sh//2,title)
                elif not flagged and travel is None:travel=(page,sx+sw//2,sy+sh//2,title)
            for badge in badges:
                if clipped_previous_submit(badge,titles):continue
                bx,by,bw,bh=rect(badge.box)
                attached=[s for s in submit if (rect(s.box)[0]<360)==(bx<360) and 180<rect(s.box)[1]-by<390]
                for button in attached:
                    sx,sy,sw,sh=rect(button.box)
                    candidates=[t for t in titles if (rect(t.box)[0]<360)==(sx<360)
                        and 210<sy-rect(t.box)[1]<350 and has_bounty_badge(t,[badge])]
                    if len(candidates)==1 and not test_title:
                        return ('重金悬赏',sx+sw//2,sy+sh//2,str(candidates[0].text))
                bounty_pending=True
            for button in submit:
                sx,sy,sw,sh=rect(button.box)
                if sy<450 or sy>1110:continue
                candidates=[t for t in titles if (rect(t.box)[0]<360)==(sx<360) and 210<sy-rect(t.box)[1]<350]
                if candidates and ordinary is None:
                    title=str(candidates[0].text)
                    ordinary=(page,sx+sw//2,sy+sh//2,title)
            if stable>=2:
                choice=(bounty_travel or travel) if test_title else (bounty_travel if bounty_pending else (ordinary or travel))
                if choice is None:raise RuntimeError('存在待完成重金悬赏或未知任务，无法安全确认入口')
                # Return to top and reproduce the recorded page, then recheck.
                for _ in range(5):
                    if not controller.post_swipe(360,330,360,1030,350).wait().succeeded:
                        raise RuntimeError('委托列表重定位回顶滑动失败')
                    time.sleep(.25)
                for _ in range(choice[0]):
                    if not controller.post_swipe(360,970,360,600,400).wait().succeeded:
                        raise RuntimeError('委托列表重定位滑动失败')
                    time.sleep(.7)
                kind=('前往重金' if choice is bounty_travel else '前往普通') if test_title else ('前往重金' if bounty_pending else ('普通委托' if ordinary else '前往普通'))
                time.sleep(1.5)
                frame=_capture(controller);self.counter(ctx,frame)
                titles=all_results(ctx.run_recognition('CommissionCardTitle',frame))
                buttons=all_results(ctx.run_recognition('CommissionForward' if kind.startswith('前往') else 'CommissionSubmit',frame))
                badges=bounty_badges(ctx,frame)
                verify_bounty_consistency(titles,badges)
                return relocate_choice(choice,kind,titles,buttons,badges)
            before=frame[160:1120:8,30:690:8,:3].astype(float)
            if not controller.post_swipe(360,970,360,600,400).wait().succeeded:raise RuntimeError('列表滚动失败')
            time.sleep(1.5);after=_capture(controller)[160:1120:8,30:690:8,:3].astype(float)
            stable=stable+1 if np.abs(before-after).mean()<4 else 0
        raise RuntimeError('委托列表扫描未到末尾')

    def run(self,context,argv):
        controller=ContextController(context)
        try:
            options=json.loads((argv.custom_action_param if argv else '') or '{}') or {}
            if not isinstance(options,dict):raise RuntimeError('委托参数格式无效')
            quota=options.get('count',4)
            if isinstance(quota,bool) or not isinstance(quota,int) or not 0<=quota<=4:
                raise RuntimeError('委托处理次数必须为0至4')
            test_map=options.get('test_map') is True
            test_title=options.get('test_title')
            if test_title and (not test_map or test_title not in ('收集','清理')):raise RuntimeError('非法测试筛选')
            if quota==0 and not test_map:
                print('[委托] 今日目标设置为0次，跳过',flush=True)
                recovery=context.run_task('NavigationRecovery');return bool(recovery and recovery.status.succeeded)
            for _ in range(8):
                before=self.counter(context,_capture(controller));time.sleep(.3)
                if self.counter(context,_capture(controller))!=before:raise RuntimeError('免费次数读数不稳定')
                done_today=4-before
                if not test_map and done_today>=quota:
                    print(f'[委托] 今日已完成 {done_today}/{quota} 次，达到目标；未使用卷轴',flush=True)
                    recovery=context.run_task('NavigationRecovery');return bool(recovery and recovery.status.succeeded)
                kind,x,y,title=self.scan(context,controller,test_title=test_title)
                frame=_capture(controller)
                if self.counter(context,frame)!=before:raise RuntimeError('提交前次数发生变化')
                if kind.startswith('前往'):
                    if not title.startswith(('清理','消灭','收集')):raise RuntimeError('委托类型尚未验证，停止')
                    self.travel(context,controller,x,y,title,kind)
                    if test_map:
                        print('[委托测试] 地图委托完成，仅测试一次，未提交和消耗卷轴',flush=True)
                        return True
                    continue
                if test_map:raise RuntimeError('测试模式只允许前往地图，禁止提交')
                buttons=all_results(context.run_recognition('CommissionSubmit',frame))
                titles=all_results(context.run_recognition('CommissionCardTitle',frame))
                badges=bounty_badges(context,frame)
                verify_bounty_consistency(titles,badges)
                x,y=confirm_current_choice(kind,x,y,title,titles,buttons,badges)
                print(f'[委托] {kind}：{title}；提交可能消耗任务要求的材料，剩余免费次数 {before}/4',flush=True)
                if not controller.post_click(x,y).wait().succeeded:raise RuntimeError('提交失败')
                after=self.after_submission(context,controller,before)
                if after!=before-1:raise RuntimeError('提交后免费次数未按预期减少，停止')
                done_today=4-after
                print(f'[委托] 今日已完成 {done_today}/{quota} 次',flush=True)
                if done_today>=quota:
                    recovery=context.run_task('NavigationRecovery');return bool(recovery and recovery.status.succeeded)
            raise RuntimeError('达到委托处理次数上限')
        except Exception as e:
            print(f'[委托] 停止：{e}；未使用卷轴或购买',flush=True);return False

    def wait(self,ctx,controller,node,seconds=12):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            hit=locate(ctx,node,_capture(controller))
            if hit:return hit
            time.sleep(.5)
        raise RuntimeError('未识别页面：'+node)

    def travel(self,ctx,controller,x,y,title,kind):
        frame=_capture(controller)
        forwards=all_results(ctx.run_recognition('CommissionForward',frame))
        titles=all_results(ctx.run_recognition('CommissionCardTitle',frame))
        badges=bounty_badges(ctx,frame)
        verify_bounty_consistency(titles,badges)
        x,y=confirm_current_choice(kind,x,y,title,titles,forwards,badges)
        if not controller.post_click(x,y).wait().succeeded:raise RuntimeError('前往点击失败')
        if title.startswith('收集'):
            # The other button synthesizes AND submits, potentially consuming a
            # scroll. Always choose acquisition, then verify the map prompt.
            self.wait(ctx,controller,'CommissionAcquireChoice')
            if not controller.post_click(205,737).wait().succeeded:raise RuntimeError('前往获取失败')
            time.sleep(.5)
        self.wait(ctx,controller,'CommissionMapConfirm')
        if not controller.post_click(493,737).wait().succeeded:raise RuntimeError('前往确认失败')
        time.sleep(2)
        self.wait(ctx,controller,'CommissionMapProgress',25)
        time.sleep(2)  # The tracker can render before map controls respond.
        if not controller.post_click(269,938).wait().succeeded:raise RuntimeError('打开委托托管失败')
        frame=_capture(controller);self.wait(ctx,controller,'CommissionCollectHostTitle' if title.startswith('收集') else 'CommissionHostTitle')
        frame=_capture(controller)
        collect=title.startswith('收集')
        done,total=read_commission_progress(ctx,frame,'CommissionCollectProgress' if collect else 'CommissionHostProgress')
        cost,available=read_ratio(ctx,frame,'CommissionCollectCost' if collect else 'CommissionHostCost')
        detail=ctx.run_recognition('CommissionCollectAmount' if collect else 'CommissionHostAmount',frame)
        values=[str(getattr(a,'text','')).strip() for a in all_results(detail)]
        if collect:
            expected=ctx.run_recognition('CommissionCollectExpected',frame)
            expected_values=[str(getattr(a,'text','')).strip() for a in all_results(expected)]
            valid_amount=values and values[0].isdigit() and 1<=int(values[0])<=20 and expected_values==[str(total-done)]
        else:valid_amount=values==[str(total-done)]
        if 0 <= available < cost and cost > 0:
            raise RuntimeError(f'体力不足：托管需要{cost}点，当前只有{available}点；请将委托排在耗尽体力的任务之前')
        if not (0<=done<total<=20 and 0<cost<=available<=300 and valid_amount):
            raise RuntimeError(f'托管进度、数量或体力不明确：{done}/{total}，{cost}/{available}，{values}')
        start=self.wait(ctx,controller,'CommissionCollectStart' if collect else 'CommissionHostStart')
        bx,by,bw,bh=rect(start.box)
        if not controller.post_click(bx+bw//2,by+bh//2).wait().succeeded:raise RuntimeError('托管启动失败')
        print(f'[委托] {kind} {title}：托管{values[0]}次，预计体力{cost}/{available}',flush=True)
        deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            time.sleep(3)
            try:
                progress,maximum=read_ratio(ctx,_capture(controller),'CommissionMapProgress')
                if maximum==total and progress==total:break
            except RuntimeError:pass
        else:raise RuntimeError('托管未确认完成，停止且不切换页面')
        # Completion counter can update before hosting ends; inspect the gear
        # and require the original Start button, not the End hosting button.
        time.sleep(2)
        if not controller.post_click(269,938).wait().succeeded:raise RuntimeError('托管结束复核失败')
        self.wait(ctx,controller,'CommissionCollectStart' if collect else 'CommissionHostStart',10)
        if not controller.post_click(360,1120).wait().succeeded:raise RuntimeError('关闭托管面板失败')
        time.sleep(.5)
        if locate(ctx,'CommissionCollectHostTitle' if collect else 'CommissionHostTitle',_capture(controller)):
            raise RuntimeError('托管面板未关闭，停止返回')
        print('[委托] 已确认地图目标完成，返回列表复核',flush=True)
        if not controller.post_click(72,1220).wait().succeeded:raise RuntimeError('退出委托地图失败')
        time.sleep(3)
        detail=ctx.run_task('NavigationRecovery')
        if not detail or not detail.status.succeeded:raise RuntimeError('返回主界面失败')
        detail=ctx.run_task('CommissionReturnMenu')
        if not detail or not detail.status.succeeded:raise RuntimeError('返回委托页面失败')
