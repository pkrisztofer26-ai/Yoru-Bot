from __future__ import annotations

from io import BytesIO
import math
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont

W, H = 960, 620
BG = (15, 17, 26)
PANEL = (28, 31, 45)
PANEL_2 = (37, 41, 58)
TEXT = (245, 247, 255)
MUTED = (165, 171, 193)
PURPLE = (116, 73, 255)
GREEN = (68, 210, 142)
RED = (238, 90, 93)
GOLD = (245, 198, 77)

BORSOD_TOKEN_META = {
    "🔩": ("FÉM", (148, 163, 184)),
    "🔌": ("RÉZ", (230, 133, 72)),
    "📺": ("TV", (117, 151, 255)),
    "🚲": ("BIC", (88, 205, 170)),
    "💵": ("$", (70, 210, 130)),
    "📦": ("LÁDA", (183, 126, 255)),
    "🗑️": ("LOM", (132, 136, 151)),
    "🧯": ("VAS", (224, 104, 104)),
    "🚓": ("JÁRŐR", (238, 90, 93)),
    "✦": ("?", GOLD),
}


def _clean_borsod_text(text: str) -> str:
    out = str(text)
    names = {"🔩": "fém", "🔌": "rézkábel", "📺": "elektronika", "🚲": "bicikli", "💵": "készpénz", "📦": "ritka loot", "🗑️": "lom", "🧯": "vas", "🚓": "járőr"}
    for token, name in names.items():
        out = out.replace(token, name)
    return out


def _draw_borsod_token(draw: ImageDraw.ImageDraw, token: str, box: tuple[int, int, int, int]) -> None:
    if token == "?":
        return
    label, accent = BORSOD_TOKEN_META.get(token, (str(token)[:5], TEXT))
    x0, y0, x1, y1 = box
    inner = (x0 + 7, y0 + 7, x1 - 7, y1 - 7)
    draw.rounded_rectangle(inner, radius=9, fill=(31, 34, 48), outline=accent, width=2)
    font = _fit(draw, label, max(22, inner[2]-inner[0]-10), start=16, minimum=10, bold=True)
    _text_center(draw, label, y0 + 22, font, accent, x0, x1)


def _font(size: int, bold: bool = False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _text_center(draw: ImageDraw.ImageDraw, text: str, y: int, font, fill=TEXT, x0: int = 0, x1: int = W):
    box = draw.textbbox((0, 0), text, font=font)
    tw = box[2] - box[0]
    draw.text(((x0 + x1 - tw) / 2 - box[0], y - box[1]), text, font=font, fill=fill)


def _fit(draw: ImageDraw.ImageDraw, text: str, width: int, start: int, minimum: int = 18, bold=True):
    for size in range(start, minimum - 1, -2):
        f = _font(size, bold)
        b = draw.textbbox((0, 0), text, font=f)
        if b[2] - b[0] <= width:
            return f
    return _font(minimum, bold)


def _owner(name: str | None) -> str:
    clean = (name or "Játékos").strip()
    if len(clean) > 26:
        clean = clean[:25] + "…"
    return clean.upper()


def _base(title: str, player: str | None, accent=PURPLE, subtitle="YORU JOBS"):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((26, 24, W - 26, H - 24), radius=28, fill=PANEL, outline=accent, width=3)
    title_f = _fit(d, title.upper(), 570, 38, 22)
    d.text((54, 50), title.upper(), font=title_f, fill=TEXT)
    sub_f = _font(19, True)
    sb = d.textbbox((0, 0), subtitle, font=sub_f)
    d.text((W - 54 - (sb[2] - sb[0]), 58), subtitle, font=sub_f, fill=accent)
    d.line((54, 105, W - 54, 105), fill=(68, 71, 91), width=2)
    owner = f"{_owner(player)} • MŰSZAK"
    of = _fit(d, owner, 700, 24, 18)
    _text_center(d, owner, 123, of, MUTED)
    return img, d


def _save_png(img: Image.Image, name: str) -> BytesIO:
    out = BytesIO(); out.name = name
    img.save(out, format="PNG", optimize=True); out.seek(0); return out


def _save_gif(frames: list[Image.Image], durations: list[int], name: str) -> BytesIO:
    out = BytesIO(); out.name = name
    frames[0].save(out, format="GIF", save_all=True, append_images=frames[1:], duration=durations, loop=0, disposal=2, optimize=True)
    out.seek(0); return out


def render_job_lobby(player_name: str, mastery_lines: list[tuple[str, str, str]]) -> BytesIO:
    img, d = _base("INTERACTIVE JOBS", player_name, PURPLE)
    cards = [(54, 174, 445, 330), (515, 174, 906, 330), (54, 350, 445, 506), (515, 350, 906, 506)]
    for (title, subtitle, level), box in zip(mastery_lines, cards):
        d.rounded_rectangle(box, radius=22, fill=PANEL_2, outline=(74, 78, 102), width=2)
        tf = _fit(d, title, box[2]-box[0]-36, 28, 18)
        _text_center(d, title, box[1]+28, tf, TEXT, box[0], box[2])
        sf = _fit(d, subtitle, box[2]-box[0]-36, 18, 14, False)
        _text_center(d, subtitle, box[1]+76, sf, MUTED, box[0], box[2])
        lf = _font(20, True)
        _text_center(d, level, box[1]+112, lf, GOLD, box[0], box[2])
    _text_center(d, "Aktív játék • jobb teljesítmény = jobb payout", 548, _font(19, True), MUTED)
    return _save_png(img, "jobs_lobby.png")


def render_warehouse(player_name: str, sequence: list[str], *, phase: str, round_no: int, correct: int, combo: int) -> BytesIO:
    img, d = _base("RAKTÁROS", player_name, (84,120,255))
    _text_center(d, f"KÖR {round_no}/5", 176, _font(22, True), (84,120,255))
    if phase == "memorize":
        _text_center(d, "JEGYEZD MEG A SORRENDET", 214, _font(24, True), TEXT)
        boxes = []
        gap, bw = 20, 170
        total = len(sequence)*bw + (len(sequence)-1)*gap
        x = (W-total)//2
        for i, token in enumerate(sequence):
            b=(x+i*(bw+gap), 284, x+i*(bw+gap)+bw, 402); boxes.append(b)
            d.rounded_rectangle(b, radius=18, fill=PANEL_2, outline=(84,120,255), width=3)
            _text_center(d, token, 318, _font(30, True), TEXT, b[0], b[2])
    else:
        _text_center(d, "MELYIK VOLT A HELYES SORREND?", 220, _font(24, True), TEXT)
        d.rounded_rectangle((215, 285, 745, 397), radius=24, fill=PANEL_2, outline=(74,78,102), width=2)
        _text_center(d, "A12  →  ?  →  ?  →  ?", 320, _font(31, True), MUTED, 215, 745)
    d.rounded_rectangle((130, 468, 830, 544), radius=18, fill=(23,25,37))
    _text_center(d, f"HELYES: {correct}   •   COMBO: x{combo}", 490, _font(22, True), GOLD)
    return _save_png(img, "warehouse_state.png")


def render_warehouse_transition(player_name: str, sequence: list[str], round_no: int) -> BytesIO:
    frames=[]
    for i in range(7):
        img,d=_base("RAKTÁROS", player_name, (84,120,255))
        _text_center(d, f"KÖR {round_no}/5 • BETÁROLÁS", 180, _font(22,True), (84,120,255))
        progress=(i+1)/7
        for n, token in enumerate(sequence):
            x0=120+n*185
            y0=int(390-120*math.sin(min(1,progress+n*0.05)*math.pi))
            d.rounded_rectangle((x0,y0,x0+145,y0+82), radius=16, fill=PANEL_2, outline=(84,120,255), width=2)
            _text_center(d, token, y0+22, _font(24,True), TEXT, x0, x0+145)
        frames.append(img)
    return _save_gif(frames, [180]*6+[520], "warehouse_shift.gif")


def render_borsod(player_name: str, board: list[str], attempts_left: int, loot_value: int, *, event: str="KERESS LOOTOT") -> BytesIO:
    img,d=_base("BORSODI LOPKODÁS",player_name,(240,165,50))
    _event = _clean_borsod_text(event).upper()
    _text_center(d,_event,174,_fit(d,_event,760,25,17),GOLD)
    size=55; gap=8; total=5*size+4*gap; x0=(W-total)//2; y0=218
    for idx, token in enumerate(board[:25]):
        r,c=divmod(idx,5); x=x0+c*(size+gap); y=y0+r*(size+gap)
        fill=(35,38,52) if token=="?" else (48,51,66)
        outline=(90,94,116) if token=="?" else (240,165,50)
        d.rounded_rectangle((x,y,x+size,y+size), radius=12, fill=fill, outline=outline, width=2)
        if token != "?":
            _draw_borsod_token(d, token, (x, y, x + size, y + size))
    d.rounded_rectangle((145,538,815,582),radius=16,fill=(23,25,37))
    _text_center(d,f"KERESÉS: {attempts_left}   •   RUN LOOT: ${loot_value:,}".replace(","," "),548,_font(18,True),MUTED)
    return _save_png(img,"borsod_state.png")


def render_route_animation(player_name: str, title: str, vehicle: str, *, accent, event: str, success: bool=True) -> BytesIO:
    frames=[]
    for i in range(10):
        img,d=_base(title,player_name,accent)
        d.line((110,350,850,350),fill=(92,96,116),width=8)
        for x in range(130,850,90): d.line((x,350,x+34,350),fill=(220,220,225),width=4)
        x=int(115+(690*(i/9)))
        # Vector vehicle: no emoji-font dependency, consistent on every host.
        body_y = 300
        d.rounded_rectangle((x-54, body_y, x+34, body_y+43), radius=10, fill=accent, outline=(235,238,248), width=2)
        d.polygon([(x+24,body_y),(x+58,body_y+12),(x+58,body_y+43),(x+24,body_y+43)], fill=accent)
        d.rectangle((x+31,body_y+8,x+50,body_y+23), fill=(166,205,229))
        d.ellipse((x-35,body_y+35,x-15,body_y+55), fill=(18,20,27), outline=(230,230,235), width=2)
        d.ellipse((x+28,body_y+35,x+48,body_y+55), fill=(18,20,27), outline=(230,230,235), width=2)
        vf=_fit(d, str(vehicle).upper(), 68, 12, 9)
        _text_center(d,str(vehicle).upper(),body_y+13,vf,(18,22,30),x-50,x+20)
        if i>=6:
            _text_center(d,event.upper(),215,_fit(d,event.upper(),720,25,17),GREEN if success else RED)
        d.rounded_rectangle((150,452,810,526),radius=18,fill=(23,25,37))
        _text_center(d,"ÚTON • DÖNTÉS → ESEMÉNY → PERFORMANCE",474,_font(20,True),MUTED)
        frames.append(img)
    return _save_gif(frames,[150,150,150,170,170,190,210,230,260,600],"route.gif")


def render_transport_state(player_name: str, title: str, *, accent, stage: int, total: int, score: int, reward: int, event: str, rating: str | None=None) -> BytesIO:
    img,d=_base(title,player_name,accent)
    if rating:
        _text_center(d,"MŰSZAK LEZÁRVA",175,_font(23,True),accent)
        d.rounded_rectangle((335,220,625,370),radius=28,fill=PANEL_2,outline=accent,width=3)
        _text_center(d,rating,240,_font(82,True),GOLD,335,625)
        _text_center(d,event.upper(),405,_fit(d,event.upper(),760,24,16),TEXT)
    else:
        _text_center(d,f"FUVAR {stage}/{total}",175,_font(22,True),accent)
        d.rounded_rectangle((150,230,810,380),radius=24,fill=PANEL_2,outline=(74,78,102),width=2)
        _text_center(d,event.upper(),270,_fit(d,event.upper(),610,29,17),TEXT,150,810)
        _text_center(d,"Válassz útvonalat az alábbi gombokkal",326,_font(18,False),MUTED,150,810)
    d.rounded_rectangle((120,478,840,553),radius=18,fill=(23,25,37))
    _text_center(d,f"PERFORMANCE: {score}/100   •   RUN: ${reward:,}".replace(","," "),500,_font(20,True),MUTED)
    return _save_png(img,"transport_state.png")

def render_borsod_reveal_animation(player_name: str, board: list[str], index: int, reveal_token: str, attempts_left: int, loot_value: int) -> BytesIO:
    frames=[]
    for step, token in enumerate(("✦","✦",reveal_token,reveal_token)):
        temp=list(board); temp[index]=token
        img,d=_base("BORSODI LOPKODÁS",player_name,(240,165,50))
        _headline = "ÁTNÉZED A HELYET…" if step < 2 else f"TALÁLAT: {_clean_borsod_text(reveal_token)}"
        _text_center(d,_headline.upper(),174,_fit(d,_headline.upper(),760,24,16),GOLD if step<2 else TEXT)
        size=55; gap=8; total=5*size+4*gap; x0=(W-total)//2; y0=218
        for idx, cell in enumerate(temp[:25]):
            r,c=divmod(idx,5); x=x0+c*(size+gap); y=y0+r*(size+gap)
            active=idx==index
            fill=(62,54,35) if active else ((35,38,52) if cell=="?" else (48,51,66))
            outline=GOLD if active else ((90,94,116) if cell=="?" else (240,165,50))
            d.rounded_rectangle((x,y,x+size,y+size),radius=12,fill=fill,outline=outline,width=3 if active else 2)
            if cell != "?":
                _draw_borsod_token(d, cell, (x, y, x + size, y + size))
        d.rounded_rectangle((145,538,815,582),radius=16,fill=(23,25,37))
        _text_center(d,f"KERESÉS: {attempts_left}   •   RUN LOOT: ${loot_value:,}".replace(","," "),548,_font(18,True),MUTED)
        frames.append(img)
    return _save_gif(frames,[180,180,280,650],"borsod_reveal.gif")

def render_job_final(player_name: str, title: str, *, accent, rating: str, score: int, reward: int, mastery_level: int, mastery_xp: int) -> BytesIO:
    img,d=_base(title,player_name,accent)
    _text_center(d,"MŰSZAK LEZÁRVA",174,_font(23,True),accent)
    d.rounded_rectangle((335,215,625,365),radius=28,fill=PANEL_2,outline=accent,width=3)
    _text_center(d,rating,238,_font(82,True),GOLD,335,625)
    cards=[(95,420,345,525),(355,420,605,525),(615,420,865,525)]
    data=[("PERFORMANCE",f"{score}/100"),("KIFIZETÉS",f"${reward:,}".replace(","," ")),("MASTERY",f"LV.{mastery_level}  +{mastery_xp} XP")]
    for box,(label,value) in zip(cards,data):
        d.rounded_rectangle(box,radius=18,fill=(23,25,37),outline=(74,78,102),width=2)
        _text_center(d,label,box[1]+18,_font(15,True),MUTED,box[0],box[2])
        vf=_fit(d,value,box[2]-box[0]-20,22,14)
        _text_center(d,value,box[1]+54,vf,TEXT,box[0],box[2])
    _text_center(d,"YORU JOBS • aktív teljesítmény, nem AFK farm",560,_font(16,False),MUTED)
    return _save_png(img,"job_final.png")
