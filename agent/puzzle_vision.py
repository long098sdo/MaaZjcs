"""Game-specific conservative CV adapters. All coordinates are normalized 720px."""
import numpy as np

def cv():
    try:import cv2;return cv2
    except ImportError:raise RuntimeError('棋盘识别需要OpenCV；缺少依赖时停止，不猜测操作')

def circuit_cells(frame):
    cv2=cv();gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
    edges=cv2.Canny(gray,35,100)
    contours,_=cv2.findContours(edges,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    boxes=[]
    for contour in contours:
        x,y,w,h=cv2.boundingRect(contour)
        if not(45<=w<=165 and 45<=h<=165 and .88<w/h<1.13 and 30<x<680 and 400<y<1050):continue
        if cv2.contourArea(contour)<w*h*.58:continue
        if any(abs(x-a)<8 and abs(y-b)<8 for a,b,_,_ in boxes):continue
        boxes.append((x,y,w,h))
    for size in sorted({round(w/8)*8 for _,_,w,_ in boxes},reverse=True):
        selected=[b for b in boxes if abs(b[2]-size)<10]
        if len(selected)<3:continue
        # Use the full stone-colour footprint to include border-split tiles and
        # irregular arms. Never silently crop a larger board to a solvable subset.
        region=frame[410:1100,30:690,:3].astype(float)
        stone=(region.min(axis=2)>95)&(region.max(axis=2)<235)&(np.ptp(region,axis=2)<80)
        yy,xx=np.where(stone)
        if len(xx)<size*size*2:continue
        x0,x1=int(xx.min())+30,int(xx.max())+30
        y0,y1=int(yy.min())+410,int(yy.max())+410
        w=int(np.median([b[2] for b in selected]));h=int(np.median([b[3] for b in selected]))
        cols=round((x1-x0+5)/(w+5));rows=round((y1-y0+5)/(h+5))
        if not (2<=rows<=6 and 2<=cols<=6):continue
        stepx=(x1-x0+1-w)/(cols-1);stepy=(y1-y0+1-h)/(rows-1)
        if not (.96*w<=stepx<=1.16*w and .96*h<=stepy<=1.16*h):continue
        xs=[round(x0+c*stepx) for c in range(cols)]
        ys=[round(y0+r*stepy) for r in range(rows)]
        if any(min(abs(x-p) for p in xs)>7 or min(abs(y-p) for p in ys)>7 for x,y,_,_ in selected):continue
        ordered=[(x,y,w,h) if 100<float(np.median(gray[y:y+h,x:x+w]))<230 else None for y in ys for x in xs]
        if sum(b is not None for b in ordered)>=len(selected):return ordered,rows,cols
        continue
    raise RuntimeError('未识别到规则能量回路棋盘')

def circuit_masks(frame,boxes):
    masks=[]
    for box in boxes:
        if box is None:
            masks.append(0)
            continue
        x,y,w,h=box
        patch=frame[y:y+h,x:x+w,:3].astype(float)
        base=float(np.median(patch.mean(axis=2)))
        bits=0
        for bit,px,py in ((1,.5,.16),(2,.84,.5),(4,.5,.84),(8,.16,.5)):
            sx,sy=int(px*w),int(py*h);radius=max(3,int(w*.07))
            sample=patch[sy-radius:sy+radius+1,sx-radius:sx+radius+1]
            dark=sample.mean(axis=2)<base-25
            blue=(sample[:,:,0]>150)&(sample[:,:,1]>105)&(sample[:,:,2]<125)
            fraction=float((dark|blue).mean())
            if fraction>.22:bits|=bit
            elif fraction>.10:raise RuntimeError('线路方向识别有歧义')
        if not bits:raise RuntimeError('存在未知/无线路石板')
        masks.append(bits)
    return masks

def classify_match3(frame,boxes,templates,threshold=.88,margin=.05):
    """Classify visible candy faces; reject unknown faces/occlusion/low margin.

    In-board skill outlines keep the same face and may amplify a legal swap.
    Their refill/effects are not predicted; callers must recapture every turn.
    """
    cv2=cv();labels=[]
    for x,y,w,h in boxes:
        patch=frame[y:y+h,x:x+w,:3]
        scores=[]
        for label,template in templates.items():
            # Allow small idle-animation offsets inside a cell, never search
            # beyond its boundaries or resize away a skill overlay.
            if patch.shape[0]<template.shape[0] or patch.shape[1]<template.shape[1]:
                scores.append((-1,label));continue
            score=float(cv2.matchTemplate(patch,template,cv2.TM_CCOEFF_NORMED).max())
            scores.append((score,label))
        scores.sort(reverse=True)
        if not scores or scores[0][0]<threshold or (len(scores)>1 and scores[0][0]-scores[1][0]<margin):
            labels.append(-1)
        else:labels.append(scores[0][1])
    return labels
