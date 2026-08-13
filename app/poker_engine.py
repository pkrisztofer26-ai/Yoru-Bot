from __future__ import annotations

import itertools
import random
from dataclasses import dataclass, field
from typing import Iterable

RANKS="23456789TJQKA"
SUITS="♠♥♦♣"


def new_deck(rng: random.Random | None=None)->list[str]:
    deck=[r+s for r in RANKS for s in SUITS]
    (rng or random.SystemRandom()).shuffle(deck)
    return deck


def _rank(card:str)->int:
    return RANKS.index(card[0])+2


def evaluate5(cards:Iterable[str])->tuple:
    cs=list(cards)
    ranks=sorted((_rank(c) for c in cs),reverse=True)
    suits=[c[1] for c in cs]
    counts={r:ranks.count(r) for r in set(ranks)}
    unique=sorted(set(ranks),reverse=True)
    if 14 in unique: unique.append(1)
    straight_high=0
    for i in range(len(unique)-4):
        seq=unique[i:i+5]
        if seq[0]-seq[4]==4:
            straight_high=seq[0]; break
    flush=len(set(suits))==1
    if flush and straight_high:return (8,straight_high)
    groups=sorted(((cnt,r) for r,cnt in counts.items()),reverse=True)
    fours=sorted((r for r,c in counts.items() if c==4),reverse=True)
    if fours:
        q=fours[0]; kicker=max(r for r in ranks if r!=q); return (7,q,kicker)
    trips=sorted((r for r,c in counts.items() if c==3),reverse=True)
    pairs=sorted((r for r,c in counts.items() if c>=2),reverse=True)
    if trips:
        t=trips[0]; pair_candidates=[r for r in pairs if r!=t]
        if pair_candidates:return (6,t,pair_candidates[0])
    if flush:return (5,*ranks)
    if straight_high:return (4,straight_high)
    if trips:
        t=trips[0]; kick=sorted((r for r in ranks if r!=t),reverse=True)[:2]; return (3,t,*kick)
    exact_pairs=sorted((r for r,c in counts.items() if c==2),reverse=True)
    if len(exact_pairs)>=2:
        p1,p2=exact_pairs[:2]; kicker=max(r for r in ranks if r not in {p1,p2}); return (2,p1,p2,kicker)
    if len(exact_pairs)==1:
        p=exact_pairs[0]; kick=sorted((r for r in ranks if r!=p),reverse=True)[:3]; return (1,p,*kick)
    return (0,*ranks)


def best_hand(cards:Iterable[str])->tuple:
    cs=list(cards)
    if len(cs)<5: raise ValueError("Legalább 5 lap kell.")
    return max(evaluate5(c) for c in itertools.combinations(cs,5))


def hand_name(score:tuple)->str:
    return ["Magas lap","Pár","Két pár","Drill","Sor","Flush","Full house","Póker","Színsor"][int(score[0])]


@dataclass
class PokerPlayer:
    user_id:int
    name:str
    stack:int
    cards:list[str]=field(default_factory=list)
    bet_round:int=0
    total_bet:int=0
    folded:bool=False
    all_in:bool=False

    @property
    def active(self)->bool:return not self.folded


@dataclass
class PokerTableState:
    table_id:str
    guild_id:int
    owner_id:int
    buy_in:int
    players:list[PokerPlayer]
    dealer:int=0
    deck:list[str]=field(default_factory=list)
    board:list[str]=field(default_factory=list)
    street:str="preflop"
    current_bet:int=0
    bb:int=0
    current_index:int=0
    acted:set[int]=field(default_factory=set)
    finished:bool=False
    last_action:str=""
    action_nonce:int=0

    def pot(self)->int:return sum(p.total_bet for p in self.players)
    def live_indices(self)->list[int]:return [i for i,p in enumerate(self.players) if not p.folded]
    def actionable_indices(self)->list[int]:return [i for i,p in enumerate(self.players) if not p.folded and not p.all_in and p.stack>0]

    def next_index(self,start:int)->int:
        n=len(self.players)
        for step in range(1,n+1):
            idx=(start+step)%n
            p=self.players[idx]
            if not p.folded and not p.all_in and p.stack>0:return idx
        return start

    def post(self,index:int,amount:int)->int:
        p=self.players[index]; pay=min(max(0,amount),p.stack); p.stack-=pay; p.bet_round+=pay; p.total_bet+=pay
        if p.stack<=0:p.all_in=True
        return pay

    def start_hand(self,rng:random.Random|None=None)->None:
        self.deck=new_deck(rng); self.board=[]; self.street="preflop"; self.current_bet=0; self.acted=set(); self.finished=False; self.last_action=""
        for p in self.players:
            p.cards=[self.deck.pop(),self.deck.pop()]; p.bet_round=0; p.total_bet=0; p.folded=False; p.all_in=False
        self.bb=max(1_000,self.buy_in//50); sb=max(500,self.bb//2)
        sb_i=(self.dealer+1)%len(self.players); bb_i=(self.dealer+2)%len(self.players) if len(self.players)>2 else self.dealer
        self.post(sb_i,sb); self.post(bb_i,self.bb); self.current_bet=max(p.bet_round for p in self.players)
        self.current_index=self.next_index(bb_i)
        self.action_nonce+=1

    def call_amount(self,index:int)->int:return max(0,self.current_bet-self.players[index].bet_round)

    def can_check(self,index:int)->bool:return self.call_amount(index)==0

    def _mark_action(self,index:int)->None:
        self.acted.add(index); self.action_nonce+=1

    def fold(self,index:int)->None:
        self.players[index].folded=True; self.last_action=f"{self.players[index].name} dobott."; self._mark_action(index); self._advance_after_action(index)

    def check_call(self,index:int)->None:
        need=self.call_amount(index); paid=self.post(index,need)
        self.last_action=f"{self.players[index].name} {'check' if need==0 else f'call {paid:,}'}"; self._mark_action(index); self._advance_after_action(index)

    def raise_to(self,index:int,target:int)->None:
        p=self.players[index]; target=max(self.current_bet+self.bb,int(target)); need=max(0,target-p.bet_round); paid=self.post(index,need)
        new_total=p.bet_round
        if new_total>self.current_bet:
            self.current_bet=new_total; self.acted={index}
        else:self.acted.add(index)
        self.last_action=f"{p.name} emelt {new_total:,}-ig." if new_total>0 else f"{p.name} all-in."; self.action_nonce+=1; self._advance_after_action(index)

    def all_in(self,index:int)->None:
        p=self.players[index]; target=p.bet_round+p.stack; self.raise_to(index,target); self.last_action=f"{p.name} ALL-IN ({p.bet_round:,})."

    def _round_complete(self)->bool:
        actionable=self.actionable_indices()
        if not actionable:return True
        return all(i in self.acted and self.players[i].bet_round==self.current_bet for i in actionable)

    def _advance_after_action(self,index:int)->None:
        if len(self.live_indices())<=1:
            self.finished=True; return
        if self._round_complete():
            self.advance_street(); return
        self.current_index=self.next_index(index)

    def _burn(self)->None:
        if self.deck:self.deck.pop()

    def advance_street(self)->None:
        for p in self.players:p.bet_round=0
        self.current_bet=0; self.acted=set()
        if self.street=="preflop":
            self._burn(); self.board.extend([self.deck.pop(),self.deck.pop(),self.deck.pop()]); self.street="flop"
        elif self.street=="flop":
            self._burn(); self.board.append(self.deck.pop()); self.street="turn"
        elif self.street=="turn":
            self._burn(); self.board.append(self.deck.pop()); self.street="river"
        else:
            self.finished=True; return
        actionable=self.actionable_indices()
        if not actionable:
            # Everyone remaining is all-in: reveal the rest immediately.
            while not self.finished:self.advance_street()
            return
        self.current_index=self.next_index(self.dealer); self.action_nonce+=1

    def showdown_payouts(self)->dict[int,int]:
        live=self.live_indices()
        if len(live)==1:return {live[0]:self.pot()}
        levels=sorted(set(p.total_bet for p in self.players if p.total_bet>0))
        payouts={i:0 for i in range(len(self.players))}; prev=0
        for level in levels:
            contributors=[i for i,p in enumerate(self.players) if p.total_bet>=level]
            pot=(level-prev)*len(contributors); prev=level
            eligible=[i for i in contributors if not self.players[i].folded]
            if not eligible or pot<=0:continue
            best=max(best_hand(self.players[i].cards+self.board) for i in eligible)
            winners=[i for i in eligible if best_hand(self.players[i].cards+self.board)==best]
            share,rem=divmod(pot,len(winners))
            for i in winners:payouts[i]+=share
            for i in winners[:rem]:payouts[i]+=1
        return payouts
