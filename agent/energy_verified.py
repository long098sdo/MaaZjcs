"""Select hosting by numeric cost and verify consumption, never by text colour."""
import json
import re
import time
from maa.custom_action import CustomAction
from collab_activity import ContextController, _capture

plans={}

def set_count(context,controller,count):
    if not controller.post_click(360,765).wait().succeeded: return False
    if not controller.post_press_key(123).wait().succeeded: return False
    for _ in range(8):
        if not controller.post_press_key(67).wait().succeeded: return False
    if not controller.post_input_text(str(count)).wait().succeeded: return False
    time.sleep(0.3)
    detail=context.run_recognition('EnergyKeyboardDone',_capture(controller))
    if not detail or not detail.hit:
        raise RuntimeError('未识别到次数输入确认按钮，不猜测点击')
    box=detail.box
    if not controller.post_click(box.x+box.w//2,box.y+box.h//2).wait().succeeded: return False
    time.sleep(0.6)
    return True

def read_ratio(context,frame,node):
    detail=context.run_recognition(node,frame)
    results=getattr(detail,'all_results',[]) if detail else []
    pairs=[]
    for result in results:
        text=re.sub(r'\s+','',str(getattr(result,'text','')))
        match=re.fullmatch(r'(\d{1,5})[/／](\d{1,5})',text)
        if match: pairs.append(tuple(map(int,match.groups())))
    if len(set(pairs))!=1:
        raise RuntimeError('无法唯一识别体力数字，停止而非猜测')
    return pairs[0]


def read_slider(context, frame):
    detail = context.run_recognition('EnergyCollectCount', frame)
    if not detail or not detail.hit:
        return None
    values = set()
    for item in detail.filtered_results:
        match = re.fullmatch(r'[采採]集次数\s*(\d{1,3})[/／](\d{1,3})', item.text)
        if match:
            values.add(tuple(map(int, match.groups())))
    if len(values) != 1:
        raise RuntimeError('未能唯一识别新版采集次数')
    return *values.pop(), detail.box


def choose_slider(context, controller, frame, slider, fixed_count):
    count, limit, box = slider
    cost, available = read_ratio(context, frame, 'EnergyCostNumbers')
    if not 0 < count <= 300 or cost <= 0 or cost % count or available > 300:
        raise RuntimeError('新版托管的次数和预计消耗不一致')
    unit = cost // count
    affordable = available // unit
    if limit != affordable or count > max(1, limit):
        raise RuntimeError(f'次数上限与体力不符：上限{limit}次，体力可用{affordable}次')
    target = affordable if fixed_count is None else fixed_count
    if target > affordable:
        raise RuntimeError(f'当前体力只够托管{affordable}次，设置为{target}次')
    while count != target and target > 0:
        take_max = target == limit
        x = 597 if take_max else 542 if target > count else 125
        expected = target if take_max else count + (1 if target > count else -1)
        if not controller.post_click(x, box.y + box.h + 31).wait().succeeded:
            raise RuntimeError('新版次数控件点击失败')
        time.sleep(.45)
        frame = _capture(controller)
        next_slider = read_slider(context, frame)
        if not next_slider or next_slider[:2] != (expected, limit):
            raise RuntimeError(f'新版次数控件未确认调整至{expected}次')
        count, _, box = next_slider
    if target:
        cost, available = read_ratio(context, frame, 'EnergyCostNumbers')
        if cost != target * unit or cost > available:
            raise RuntimeError(f'新版托管预计消耗复核失败：{cost}/{available}，目标{target}次')
    return target, unit, available


class EnergySelectAll(CustomAction):
    def run(self,context,argv):
        task_id=argv.task_detail.task_id
        plans.pop(task_id,None)
        try:
            options = json.loads(getattr(argv, 'custom_action_param', None) or 'null') or {}
            fixed = options.get('count')
            if fixed is not None:
                if not re.fullmatch(r'[1-9][0-9]{0,2}', str(fixed)) or int(fixed) > 300:
                    raise RuntimeError('固定次数应为1到300的整数')
                fixed = int(fixed)
            controller=ContextController(context)
            frame = _capture(controller)
            slider = read_slider(context, frame)
            if slider:
                count, unit, available = choose_slider(context, controller, frame, slider, fixed)
                plans[task_id] = {'before': available, 'unit': unit, 'cost': count * unit, 'all': fixed is None}
                print(f'[体力复核] 新版托管已确认{count}次，预计消耗{count * unit}/{available}', flush=True)
                if count == 0:
                    if not context.override_pipeline({'EnergyExhaustProceed': {'next': ['EnergyReturnToMain']}}):
                        raise RuntimeError('无法结束体力不足的任务')
                return True
            if fixed is not None:
                return set_count(context, controller, fixed)
            if not set_count(context,controller,1): return False
            unit,available=read_ratio(context,_capture(controller),'EnergyCostNumbers')
            if unit<=0 or available>300: raise RuntimeError('体力数据超出范围')
            plans[argv.task_detail.task_id]={'before':available,'unit':unit,'cost':0,'all':True}
            if unit>available:
                print(f'[体力复核] 当前{available}，单次需{unit}，不启动托管',flush=True)
                ok=context.override_pipeline({'EnergyExhaustProceed':{'next':['EnergyReturnToMain']}})
                if not ok: plans.pop(task_id,None)
                return ok
            count=available//unit
            # Input directly, then prove the displayed total cost, rather than
            # increasing until a red pixel appears (or touching purchase controls).
            if not set_count(context,controller,count):
                plans.pop(task_id,None)
                return False
            cost,current=read_ratio(context,_capture(controller),'EnergyCostNumbers')
            if current<cost or cost!=unit*count or current<available or current-cost>=unit:
                raise RuntimeError(f'次数输入未生效或余量不符：{cost}/{current}，目标{count}次')
            plans[argv.task_detail.task_id].update(cost=cost)
            print(f'[体力复核] 已确认{count}次，预计消耗{cost}/{current}',flush=True)
            return True
        except Exception as error:
            plans.pop(task_id,None)
            print(f'[体力复核] 选择失败：{error}',flush=True)
            return False

class EnergyRecordPlan(CustomAction):
    def run(self,context,argv):
        try:
            cost,available=read_ratio(context,_capture(ContextController(context)),'EnergyCostNumbers')
            if not 0<cost<=available<=300: return False
            plan=plans.get(argv.task_detail.task_id,{})
            plan.update(before=available,cost=cost)
            plans[argv.task_detail.task_id]=plan
            return True
        except Exception as error:
            print(f'[体力复核] 启动前未取得消耗依据：{error}',flush=True)
            return False

class EnergyVerifyConsumption(CustomAction):
    def run(self,context,argv):
        try:
            plan=plans.get(argv.task_detail.task_id)
            if not plan: raise RuntimeError('没有本轮启动前的体力记录')
            remaining,maximum=read_ratio(context,_capture(ContextController(context)),'EnergyMainNumbers')
            if maximum!=300: raise RuntimeError('主界面体力上限无法确认')
            # Allow at most three regenerated points during the bounded wait.
            if plan['before']-remaining<max(0,plan['cost']-3):
                raise RuntimeError(f'实际体力减少不足：{plan["before"]}→{remaining}，计划{plan["cost"]}')
            if plan.get('all') and remaining>=plan['unit']+3:
                raise RuntimeError(f'仍剩{remaining}体力，不能判定耗尽')
            print(f'[体力复核] 实际体力{plan["before"]}→{remaining}，消耗复核通过',flush=True)
            plans.pop(argv.task_detail.task_id,None)
            return True
        except Exception as error:
            print(f'[体力复核] 未完成：{error}',flush=True)
            return False


class EnergyWaitConsumption(CustomAction):
    def run(self,context,argv):
        plan=plans.get(argv.task_detail.task_id)
        if not plan: return False
        if plan['cost']==0:
            return True
        deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            try:
                remaining,maximum=read_ratio(context,_capture(ContextController(context)),'EnergyMainNumbers')
                enough=plan['before']-remaining>=max(0,plan['cost']-3)
                exhausted=not plan.get('all') or remaining<plan['unit']+3
                if maximum==300 and enough and exhausted:
                    print('[体力复核] 已达到计划消耗，才允许返回主界面',flush=True)
                    return True
                print(f'[体力复核] 采集未结束，当前剩{remaining}，继续等待不切页',flush=True)
            except RuntimeError:
                print('[体力复核] 暂未读到体力，继续等待，不点击返回',flush=True)
            time.sleep(10)
        print('[体力复核] 延长等待3分钟仍未完成，停止而不切页',flush=True)
        return False
