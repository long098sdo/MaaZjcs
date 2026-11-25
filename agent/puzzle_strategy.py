"""Original solvers; no third-party code is vendored.

Research references (different game rules, so algorithms are adapted, not copied):
https://github.com/Lephat902/PipesSolver — edge compatibility / connectivity.
https://github.com/applidium/CandyCrushSolver — vision then legal move enumeration.
https://github.com/qenu/match3-solver — candidate ranking and cascade simulation.
"""
from collections import Counter
import time

# N,E,S,W; pieces are swapped, NEVER rotated in Energy Circuit.
BITS=(1,2,4,8)
DELTAS=((-1,0),(0,1),(1,0),(0,-1))

def connected(board,rows,cols):
    if len(board)!=rows*cols:return False
    active={i for i,piece in enumerate(board) if piece}
    if not active:return False
    for i,piece in enumerate(board):
        r,c=divmod(i,cols)
        for k,(dr,dc) in enumerate(DELTAS):
            nr,nc=r+dr,c+dc
            on=bool(piece&BITS[k])
            if not (0<=nr<rows and 0<=nc<cols):
                if on:return False
            elif on!=bool(board[nr*cols+nc]&BITS[(k+2)%4]):return False
    seen={min(active)};stack=list(seen)
    while stack:
        i=stack.pop();r,c=divmod(i,cols)
        for k,(dr,dc) in enumerate(DELTAS):
            if board[i]&BITS[k]:
                j=(r+dr)*cols+c+dc
                if j not in seen:seen.add(j);stack.append(j)
    return active<=seen

def solve_circuit(pieces,rows,cols,seconds=5,max_nodes=200000):
    if len(pieces)!=rows*cols or any(not isinstance(p,int) or p<0 or p>15 for p in pieces):
        raise ValueError('invalid circuit pieces')
    if connected(pieces,rows,cols):return list(pieces)
    # Zero denotes a missing board cell, not a movable blank tile.
    counts=Counter(p for p in pieces if p);board=[None if p else 0 for p in pieces]
    deadline=time.monotonic()+seconds;nodes=0
    def domain(i):
        r,c=divmod(i,cols);out=[]
        for piece,count in counts.items():
            if not count:continue
            valid=True
            for k,(dr,dc) in enumerate(DELTAS):
                nr,nc=r+dr,c+dc;on=bool(piece&BITS[k])
                if not (0<=nr<rows and 0<=nc<cols):
                    if on:valid=False;break
                else:
                    other=board[nr*cols+nc]
                    if other is not None and on!=bool(other&BITS[(k+2)%4]):valid=False;break
            if valid:out.append(piece)
        return out
    def search(left):
        nonlocal nodes
        nodes+=1
        if nodes>max_nodes or time.monotonic()>deadline:raise TimeoutError('circuit search budget reached')
        if not left:return list(board) if connected(board,rows,cols) else None
        choices=[(domain(i),i) for i in left]
        values,i=min(choices,key=lambda pair:len(pair[0]))
        for piece in values:
            board[i]=piece;counts[piece]-=1
            result=search(left-{i})
            if result is not None:return result
            counts[piece]+=1;board[i]=None
        return None
    return search({i for i,p in enumerate(pieces) if p})

def swap_plan(current,target):
    if Counter(current)!=Counter(target):raise ValueError('piece inventory mismatch')
    work=list(current);moves=[]
    for i,wanted in enumerate(target):
        if work[i]==wanted:continue
        j=next(j for j in range(i+1,len(work)) if work[j]==wanted)
        moves.append((j,i));work[i],work[j]=work[j],work[i]
    return moves

def matches(board):
    """Return all straight 3+ matches. Unknown (-1) is never a candy."""
    rows=len(board);cols=len(board[0]) if rows else 0;hit=set()
    for r in range(rows):
        for c in range(cols):
            v=board[r][c]
            if v is None or v<0:continue
            for dr,dc in ((1,0),(0,1)):
                cells=[];nr,nc=r,c
                while nr<rows and nc<cols and board[nr][nc]==v:
                    cells.append((nr,nc));nr+=dr;nc+=dc
                if len(cells)>=3:hit.update(cells)
    return hit

def rank_match3(board):
    """Score only observed ordinary pieces; no invented random refill or boosters.

    First priority: immediate matches, then 4/5-piece special creation, then
    deterministic falling-piece cascades. Special/unknown pieces are excluded.
    """
    if not board or not board[0] or any(len(row)!=len(board[0]) for row in board):return []
    if any(v is None or v<0 for row in board for v in row):return []
    if matches(board):return [] # Board still resolving: wait, don't drag.
    rows,cols=len(board),len(board[0]);ranked=[]
    for r in range(rows):
        for c in range(cols):
            for dr,dc in ((0,1),(1,0)):
                nr,nc=r+dr,c+dc
                if nr>=rows or nc>=cols or board[r][c]==board[nr][nc]:continue
                trial=[list(row) for row in board]
                trial[r][c],trial[nr][nc]=trial[nr][nc],trial[r][c]
                hit=matches(trial)
                if not hit or not ({(r,c),(nr,nc)}&hit):continue
                score=len(hit)*10
                # Prefer moves making long lines over plain triples.
                for rr,cc in hit:
                    for ar,ac in ((1,0),(0,1)):
                        line=0;y,x=rr,cc
                        while y<rows and x<cols and (y,x) in hit and trial[y][x]==trial[rr][cc]:
                            line+=1;y+=ar;x+=ac
                        if line>=4:score+=15*(line-3)
                for _ in range(5):
                    for y,x in hit:trial[y][x]=-1
                    for x in range(cols):
                        kept=[trial[y][x] for y in range(rows) if trial[y][x]>=0]
                        col=[-1]*(rows-len(kept))+kept
                        for y in range(rows):trial[y][x]=col[y]
                    hit=matches(trial)
                    if not hit:break
                    score+=len(hit)*12
                ranked.append((score,(r,c),(nr,nc)))
    return sorted(ranked,key=lambda item:(-item[0],item[1],item[2]))
