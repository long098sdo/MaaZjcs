"""Energy Circuit: swap-only solving with screenshot validation and no items."""
import time
import re
from types import SimpleNamespace
from maa.custom_action import CustomAction
from collab_activity import ContextController,_capture,_click_box,_scan_available,_wait_recognition
from navigation_guard import locate
from puzzle_vision import circuit_cells,circuit_masks
from puzzle_strategy import solve_circuit,swap_plan
from puzzle_vision import cv
import numpy as np

def _reward_checks(frame,box):
    """Three separate yellow check marks below a fully visible stage label."""
    if isinstance(box,(list,tuple)):
        box=SimpleNamespace(x=box[0],y=box[1],w=box[2],h=box[3])
    x=max(0,box.x+box.w//2-135);right=min(720,x+270)
    y=box.y+box.h;bottom=y+100
    if bottom>1160:return False
    hsv=cv().cvtColor(frame[y:bottom,x:right,:3],cv().COLOR_BGR2HSV)
    mask=cv().inRange(hsv,(20,70,140),(40,255,255))
    _,_,stats,_=cv().connectedComponentsWithStats(mask)
    marks=sorted((int(s[0]+s[2]/2),int(s[1]+s[3]/2)) for s in stats[1:] if 27<=s[2]<=42 and 20<=s[3]<=35 and s[4]>=350)
    return any(65<=b[0]-a[0]<=95 and 65<=c[0]-b[0]<=95 and max(a[1],b[1],c[1])-min(a[1],b[1],c[1])<=8 for a,b,c in zip(marks,marks[1:],marks[2:]))

def _scan_circuit(context):
    """Use overlapping viewports, and accept badges only above a circuit label."""
    controller=ContextController(context)
    if not _wait_recognition(context,'CircuitList',12):raise RuntimeError('未确认谜题列表')
    for _ in range(6):
        if not controller.post_swipe(360,300,360,950,350).wait().succeeded:raise RuntimeError('返回列表顶部失败')
        time.sleep(.3)
    if not _wait_recognition(context,'CircuitLevelCaption',15):raise RuntimeError('未发现能量回路关卡标题')
    stable=0;verified=set();seen=set();end_seen=False
    for _ in range(32):
        frame=_capture(controller)
        captions=context.run_recognition('CircuitLevelCaption',frame)
        frame_numbers=set()
        for item in getattr(captions,'filtered_results',[]) if captions else []:
            match=re.search(r'能量回路\s*(\d+)',str(getattr(item,'text','')))
            if match:
                number=int(match.group(1));frame_numbers.add(number);seen.add(number)
                if _reward_checks(frame,item.box):verified.add(number)
        # The real map places the first cannon puzzle immediately after level 6;
        # requiring both labels together confirms the end of the circuit section.
        if 6 in frame_numbers and locate(context,'CircuitNextMode',frame):end_seen=True
        red=context.run_recognition('CircuitAvailable',frame)
        if red and red.hit:
            b=red.box
            # On the real page the red badge is near the tile's upper-right;
            # the associated caption is roughly 100–300 px below it.
            x=max(0,b.x-250);y=b.y+70
            if y<1120:
                roi=[x,y,min(300,720-x),min(300,1160-y)]
                caption=context.run_recognition('CircuitLevelCaption',frame,{'CircuitLevelCaption':{'recognition':{'param':{'roi':roi}}}})
                if caption and caption.hit:return red
        if stable>=2:
            if end_seen and seen==set(range(1,7)) and verified==seen:
                print('[能量回路] 回路1–6均已逐关核实三个奖励黄勾',flush=True)
                return 'complete'
            return None
        before=frame[150:1080:8,40:680:8,:3].astype(float)
        if not controller.post_swipe(360,800,360,550,450).wait().succeeded:raise RuntimeError('列表滚动失败')
        time.sleep(.8)
        after=_capture(controller)[150:1080:8,40:680:8,:3].astype(float)
        stable=stable+1 if float(np.abs(before-after).mean())<4 else 0
    raise RuntimeError('关卡扫描超限')

class CircuitRunner(CustomAction):
    def run(self,context,argv):
        controller=ContextController(context)
        try:
            marker=_scan_available(context,'CircuitEventEntry','CollabEventList','CollabEventList')
            if not marker:
                raise RuntimeError('未找到菲涅克的谜题入口，无法判断活动状态')
            if not _click_box(controller,marker.box):return False
            time.sleep(1)
            for level in range(15):
                marker=_scan_circuit(context)
                if marker=='complete':
                    result=context.run_task('NavigationRecovery')
                    return bool(result and result.status.succeeded)
                if not marker:
                    # A missing badge is not proof that all unlocked levels
                    # were cleared: it may be off-screen, obscured or changed.
                    # Fail closed until each level has positive completion or
                    # locked-state evidence, rather than reporting success.
                    raise RuntimeError(f'本轮完成{level}关；未发现红点，但无法核实所有开放关卡的完成状态')
                b=marker.box
                if not controller.post_click(max(90,b.x-90),min(1040,b.y+90)).wait().succeeded:return False
                time.sleep(1)
                if not locate(context,'CircuitBoardTitle',_capture(controller)):raise RuntimeError('未确认回路关卡，禁止点击')
                frame=_capture(controller);boxes,rows,cols=circuit_cells(frame)
                current=circuit_masks(frame,boxes)
                target=solve_circuit(current,rows,cols)
                if target is None:raise RuntimeError(f'线路识别无法组成连通回路：{current}')
                moves=swap_plan(current,target)
                print(f'[能量回路] 已识别{rows}×{cols}石板，计算{len(moves)}次交换',flush=True)
                for source,destination in moves:
                    if not locate(context,'CircuitBoardTitle',_capture(controller)):raise RuntimeError('交换前关卡页面已变化')
                    for cell in (source,destination):
                        x,y,w,h=boxes[cell]
                        if not controller.post_click(x+w//2,y+h//2).wait().succeeded:return False
                        time.sleep(.25)
                    time.sleep(.7)
                    current[source],current[destination]=current[destination],current[source]
                    frame=_capture(controller)
                    if locate(context,'SpookyRewardPopup',frame):break
                    if circuit_masks(frame,boxes)!=current:raise RuntimeError('交换后棋盘与预测不一致，停止而非连点')
                deadline=time.monotonic()+8
                while time.monotonic()<deadline:
                    frame=_capture(controller)
                    exit_button=locate(context,'CircuitSuccessExit',frame)
                    if locate(context,'CircuitSuccessTitle',frame) and exit_button:
                        if not _click_box(controller,exit_button.box):return False
                        time.sleep(1)
                        break
                    time.sleep(.4)
                else:raise RuntimeError('没有通关领奖证据，不标记完成')
                frame=_capture(controller)
                if locate(context,'CircuitBoardTitle',frame):
                    controller.post_click(72,1220).wait();time.sleep(.7)
                deadline=time.monotonic()+6
                while time.monotonic()<deadline and not locate(context,'CircuitList',_capture(controller)):time.sleep(.4)
                if not locate(context,'CircuitList',_capture(controller)):raise RuntimeError('未返回关卡列表')
                print('[能量回路] 通关并领取奖励，返回列表复核',flush=True)
            raise RuntimeError('达到15关上限')
        except Exception as error:
            print(f'[能量回路] 失败：{error}；未使用道具',flush=True)
            return False
