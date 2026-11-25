"""Candy night: observed-face swaps only; recapture after every cascade."""
import time
from pathlib import Path
import numpy as np
from maa.custom_action import CustomAction
from collab_activity import ContextController,_capture,_click_box,_scan_available
from navigation_guard import locate
from puzzle_vision import cv,classify_match3
from puzzle_strategy import rank_match3

BOXES=[(135+92*c,313+92*r,84,84) for r in range(8) for c in range(5)]

def templates():
    root=Path(__file__).resolve().parents[1]/'resource/base/image/match3'
    return {i:cv().imdecode(np.fromfile(f,dtype=np.uint8),1) for i,f in enumerate(sorted(root.glob('*.png')))}

class Match3Runner(CustomAction):
    def run(self,context,argv):
        controller=ContextController(context)
        try:
            if not locate(context,'SpookyHub',_capture(controller)):
                marker=_scan_available(context,'CandyEvent','CollabEventList','CollabEventList')
                if not marker:
                    raise RuntimeError('未找到惊魂派对入口，无法确认活动状态')
                if not _click_box(controller,marker.box):return False
                time.sleep(1.5)
            if not locate(context,'SpookyHub',_capture(controller)):raise RuntimeError('未确认惊魂派对')
            controller.post_click(300,1218).wait();time.sleep(.8)
            for node in ('CandyEntry','CandyStages'):
                deadline=time.monotonic()+8
                while time.monotonic()<deadline:
                    button=locate(context,node,_capture(controller))
                    if button:break
                    time.sleep(.4)
                else:raise RuntimeError('未识别入口：'+node)
                if not _click_box(controller,button.box):return False
                time.sleep(1.5)
            for level in range(15):
                marker=_scan_available(context,'CandyAvailable','CandyList','CandyLevelCaption')
                if not marker:
                    raise RuntimeError(f'已扫描关卡列表，但无红点不足以证明全部完成；本轮完成{level}关')
                b=marker.box
                if not controller.post_click(max(90,b.x-90),min(1040,b.y+90)).wait().succeeded:return False
                time.sleep(1.5)
                if not self.play(context,controller):return False
                frame=_capture(controller)
                button=locate(context,'CandySuccessExit',frame)
                if not locate(context,'CandyReward',frame) or not button:raise RuntimeError('没有通关奖励与退出依据')
                if not _click_box(controller,button.box):return False
                time.sleep(1)
                if not locate(context,'CandyList',_capture(controller)):raise RuntimeError('领奖后未返回列表')
            raise RuntimeError('达到15关上限')
        except Exception as error:
            print(f'[糖果消消夜] 失败：{error}；未使用外部道具/购买',flush=True)
            return False

    def play(self,context,controller):
        try:
            ts=templates()
            if len(ts)!=5:raise RuntimeError('缺少已校准的五类棋子')
            frame=_capture(controller)
            if locate(context,'CandyLevel1Board',frame):
                rows,cols,x0,y0=8,5,177,355
            elif locate(context,'CandyLevel2Board',frame):
                rows,cols,x0,y0=9,6,130,310
            else:raise RuntimeError('该关卡棋盘布局尚未实测，停止操作')
            boxes=[(x0+92*c-42,y0+92*r-42,84,84) for r in range(rows) for c in range(cols)]
            previous=None;unchanged=0
            for step in range(120):
                deadline=time.monotonic()+12
                last=None
                while time.monotonic()<deadline:
                    frame=_capture(controller)
                    if locate(context,'CandySuccess',frame):
                        print(f'[糖果消消夜] 已确认通关，完成{step}次交换',flush=True)
                        return True
                    if not locate(context,'CandyBoard',frame):raise RuntimeError('未确认关卡棋盘')
                    flat=classify_match3(frame,boxes,ts)
                    board=[flat[i:i+cols] for i in range(0,rows*cols,cols)]
                    moves=rank_match3(board)
                    if moves and flat==last:break
                    last=flat;time.sleep(.5)
                else:raise RuntimeError('棋盘未知、仍在消除或无已识别合法交换，停止')
                unchanged=unchanged+1 if flat==previous else 0
                if unchanged>=2:raise RuntimeError('交换后棋盘未变化，停止重试')
                previous=flat
                score,source,target=moves[0]
                # Board-generated skills may amplify a normal legal match. We
                # never predict their random refill; next move uses a new frame.
                r,c=source;y,x=target
                if not controller.post_swipe(x0+92*c,y0+92*r,x0+92*x,y0+92*y,300).wait().succeeded:return False
                print(f'[糖果消消夜] 第{step+1}步 {source} → {target}，候选评分{score}',flush=True)
                time.sleep(1.5)
            raise RuntimeError('达到120步上限，未标记完成')
        except Exception as error:
            print(f'[糖果消消夜] 失败：{error}；未使用外部道具/购买',flush=True)
            return False
