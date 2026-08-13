from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class JobUILayout:
    outer: tuple[int, int, int, int] = (26, 24, 934, 596)
    header_rule_y: int = 105
    owner_y: int = 123
    content: tuple[int, int, int, int] = (70, 158, 890, 405)
    hud: tuple[int, int, int, int] = (95, 420, 865, 525)
    final_rating: tuple[int, int, int, int] = (335, 215, 625, 365)
    final_cards_y0: int = 420
    final_cards_y1: int = 525
    footer_y: int = 560


JOB_UI = JobUILayout()

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


def _text_center_box(draw: ImageDraw.ImageDraw, text: str, box: tuple[int, int, int, int], font, fill=TEXT):
    """True x/y centering inside a rectangle, independent of glyph ascenders/descenders."""
    x0, y0, x1, y1 = box
    bounds = draw.textbbox((0, 0), text, font=font)
    tw = bounds[2] - bounds[0]
    th = bounds[3] - bounds[1]
    x = x0 + (x1 - x0 - tw) / 2 - bounds[0]
    y = y0 + (y1 - y0 - th) / 2 - bounds[1]
    draw.text((x, y), text, font=font, fill=fill)


def _text_width(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    b = draw.textbbox((0, 0), str(text), font=font)
    return max(0, b[2] - b[0])


def _ellipsize(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> str:
    text = str(text).strip()
    if _text_width(draw, text, font) <= width:
        return text
    suffix = "…"
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        candidate = text[:mid].rstrip() + suffix
        if _text_width(draw, candidate, font) <= width:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo].rstrip() + suffix


def _wrap_for_font(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> list[str]:
    paragraphs = str(text).replace("\r", "").split("\n")
    lines: list[str] = []
    for paragraph in paragraphs:
        words = paragraph.strip().split()
        if not words:
            if lines:
                lines.append("")
            continue
        current = ""
        for word in words:
            # Protect the canvas even from a pathological unbroken token.
            word = _ellipsize(draw, word, font, width)
            candidate = word if not current else f"{current} {word}"
            if _text_width(draw, candidate, font) <= width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
    return lines or [""]


def _draw_wrapped_center_box(
    draw: ImageDraw.ImageDraw,
    text: str,
    box: tuple[int, int, int, int],
    *,
    start: int,
    minimum: int = 12,
    max_lines: int = 2,
    fill=TEXT,
    bold: bool = True,
    spacing: int = 4,
):
    """Fit + wrap dynamic text into a strict safe box without canvas overflow."""
    x0, y0, x1, y1 = box
    width = max(1, x1 - x0)
    height = max(1, y1 - y0)
    chosen = None
    chosen_lines: list[str] = []
    chosen_line_h = 0
    for size in range(start, minimum - 1, -1):
        font = _font(size, bold)
        lines = _wrap_for_font(draw, text, font, width)
        probe = draw.textbbox((0, 0), "Ag", font=font)
        line_h = max(1, probe[3] - probe[1])
        total_h = len(lines) * line_h + max(0, len(lines) - 1) * spacing
        if len(lines) <= max_lines and total_h <= height:
            chosen, chosen_lines, chosen_line_h = font, lines, line_h
            break
    if chosen is None:
        chosen = _font(minimum, bold)
        lines = _wrap_for_font(draw, text, chosen, width)
        if len(lines) > max_lines:
            kept = lines[: max(0, max_lines - 1)]
            rest = " ".join(lines[max(0, max_lines - 1):])
            lines = kept + [_ellipsize(draw, rest, chosen, width)]
        chosen_lines = lines[:max_lines]
        probe = draw.textbbox((0, 0), "Ag", font=chosen)
        chosen_line_h = max(1, probe[3] - probe[1])
    total_h = len(chosen_lines) * chosen_line_h + max(0, len(chosen_lines) - 1) * spacing
    y = y0 + (height - total_h) / 2
    for line in chosen_lines:
        bounds = draw.textbbox((0, 0), line, font=chosen)
        tw = bounds[2] - bounds[0]
        tx = x0 + (width - tw) / 2 - bounds[0]
        draw.text((tx, y - bounds[1]), line, font=chosen, fill=fill)
        y += chosen_line_h + spacing
    return chosen


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
    d.rounded_rectangle(JOB_UI.outer, radius=28, fill=PANEL, outline=accent, width=3)
    title_f = _fit(d, title.upper(), 570, 38, 22)
    d.text((54, 50), title.upper(), font=title_f, fill=TEXT)
    sub_f = _font(19, True)
    sb = d.textbbox((0, 0), subtitle, font=sub_f)
    d.text((W - 54 - (sb[2] - sb[0]), 58), subtitle, font=sub_f, fill=accent)
    d.line((54, JOB_UI.header_rule_y, W - 54, JOB_UI.header_rule_y), fill=(68, 71, 91), width=2)
    owner = f"{_owner(player)} • MŰSZAK"
    of = _fit(d, owner, 700, 24, 18)
    _text_center(d, owner, JOB_UI.owner_y, of, MUTED)
    return img, d


def _save_png(img: Image.Image, name: str) -> BytesIO:
    out = BytesIO(); out.name = name
    img.save(out, format="PNG", optimize=True); out.seek(0); return out


def _save_gif(frames: list[Image.Image], durations: list[int], name: str) -> BytesIO:
    out = BytesIO(); out.name = name
    frames[0].save(out, format="GIF", save_all=True, append_images=frames[1:], duration=durations, loop=0, disposal=2, optimize=True)
    out.seek(0); return out


def render_job_lobby(player_name: str, mastery_lines: list[tuple[str, str, str]], *, status: str = "MŰSZAK ELÉRHETŐ") -> BytesIO:
    img, d = _base("INTERACTIVE JOBS", player_name, PURPLE)
    cards = [(54, 168, 445, 318), (515, 168, 906, 318), (54, 334, 445, 484), (515, 334, 906, 484)]
    for (title, subtitle, level), box in zip(mastery_lines, cards):
        d.rounded_rectangle(box, radius=22, fill=PANEL_2, outline=(74, 78, 102), width=2)
        _draw_wrapped_center_box(d, title, (box[0]+18, box[1]+18, box[2]-18, box[1]+58), start=27, minimum=17, max_lines=1, fill=TEXT)
        _draw_wrapped_center_box(d, subtitle, (box[0]+18, box[1]+64, box[2]-18, box[1]+102), start=17, minimum=12, max_lines=1, fill=MUTED, bold=False)
        _draw_wrapped_center_box(d, level, (box[0]+18, box[1]+105, box[2]-18, box[3]-12), start=20, minimum=13, max_lines=1, fill=GOLD)
    status_box=(170,505,790,548)
    d.rounded_rectangle(status_box,radius=15,fill=(23,25,37),outline=(74,78,102),width=1)
    _draw_wrapped_center_box(d,status.upper(),(status_box[0]+14,status_box[1]+4,status_box[2]-14,status_box[3]-4),start=17,minimum=12,max_lines=1,fill=GOLD)
    _draw_wrapped_center_box(d,"Válassz egy munkát • egy teljesített műszak = közös 2 órás cooldown",(80,553,880,584),start=15,minimum=11,max_lines=1,fill=MUTED,bold=False)
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
        _draw_wrapped_center_box(d, "MELYIK VOLT A HELYES SORREND?", (150, 204, 810, 252), start=24, minimum=16, max_lines=1, fill=TEXT)
        clue_box=(215, 285, 745, 397)
        d.rounded_rectangle(clue_box, radius=24, fill=PANEL_2, outline=(74,78,102), width=2)
        clue = f"{sequence[0] if sequence else '?'}  →  ?  →  ?  →  ?"
        _draw_wrapped_center_box(d, clue, (clue_box[0]+24, clue_box[1]+18, clue_box[2]-24, clue_box[3]-18), start=31, minimum=18, max_lines=1, fill=MUTED)
    score_box=(130, 468, 830, 544)
    d.rounded_rectangle(score_box, radius=18, fill=(23,25,37))
    _draw_wrapped_center_box(d, f"HELYES: {correct}   •   COMBO: x{combo}", (score_box[0]+18,score_box[1]+8,score_box[2]-18,score_box[3]-8), start=22, minimum=15, max_lines=1, fill=GOLD)
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
    return _save_gif(frames, [260,260,280,300,320,360,900], "warehouse_shift.gif")


def render_borsod(player_name: str, board: list[str], attempts_left: int, loot_value: int, *, event: str="KERESS LOOTOT") -> BytesIO:
    img,d=_base("BORSODI LOPKODÁS",player_name,(240,165,50))
    event_box=(80,158,880,210)
    d.rounded_rectangle(event_box,radius=16,fill=(23,25,37),outline=(87,78,58),width=1)
    _event=_clean_borsod_text(event).upper()
    _draw_wrapped_center_box(d,_event,(event_box[0]+18,event_box[1]+5,event_box[2]-18,event_box[3]-5),start=20,minimum=12,max_lines=2,fill=GOLD)
    size=55; gap=8; total=5*size+4*gap; x0=(W-total)//2; y0=224
    for idx, token in enumerate(board[:25]):
        r,c=divmod(idx,5); x=x0+c*(size+gap); y=y0+r*(size+gap)
        fill=(35,38,52) if token=="?" else (48,51,66)
        outline=(90,94,116) if token=="?" else (240,165,50)
        d.rounded_rectangle((x,y,x+size,y+size), radius=12, fill=fill, outline=outline, width=2)
        if token != "?":
            _draw_borsod_token(d, token, (x, y, x + size, y + size))
    hud=(145,542,815,582)
    d.rounded_rectangle(hud,radius=16,fill=(23,25,37))
    hud_text=f"KERESÉS: {attempts_left}   •   RUN LOOT: ${loot_value:,}".replace(","," ")
    _draw_wrapped_center_box(d,hud_text,(hud[0]+15,hud[1]+3,hud[2]-15,hud[3]-3),start=18,minimum=11,max_lines=1,fill=MUTED)
    return _save_png(img,"borsod_state.png")


def render_route_animation(player_name: str, title: str, vehicle: str, *, accent, event: str, success: bool=True) -> BytesIO:
    frames=[]
    for i in range(10):
        img,d=_base(title,player_name,accent)
        event_box=(100,172,860,252)
        if i>=6:
            d.rounded_rectangle(event_box,radius=18,fill=(23,25,37),outline=GREEN if success else RED,width=1)
            _draw_wrapped_center_box(d,str(event).upper(),(event_box[0]+20,event_box[1]+8,event_box[2]-20,event_box[3]-8),start=22,minimum=13,max_lines=2,fill=GREEN if success else RED)
        else:
            _draw_wrapped_center_box(d,"ÚTON VAGY…",event_box,start=22,minimum=15,max_lines=1,fill=accent)
        road_y=362
        d.line((110,road_y,850,road_y),fill=(92,96,116),width=8)
        for xline in range(130,850,90): d.line((xline,road_y,xline+34,road_y),fill=(220,220,225),width=4)
        x=int(115+(690*(i/9)))
        body_y=312
        d.rounded_rectangle((x-54,body_y,x+34,body_y+43),radius=10,fill=accent,outline=(235,238,248),width=2)
        d.polygon([(x+24,body_y),(x+58,body_y+12),(x+58,body_y+43),(x+24,body_y+43)],fill=accent)
        d.rectangle((x+31,body_y+8,x+50,body_y+23),fill=(166,205,229))
        d.ellipse((x-35,body_y+35,x-15,body_y+55),fill=(18,20,27),outline=(230,230,235),width=2)
        d.ellipse((x+28,body_y+35,x+48,body_y+55),fill=(18,20,27),outline=(230,230,235),width=2)
        vf=_fit(d,str(vehicle).upper(),68,12,9)
        _text_center_box(d,str(vehicle).upper(),(x-50,body_y+7,x+20,body_y+35),vf,(18,22,30))
        foot=(150,458,810,526)
        d.rounded_rectangle(foot,radius=18,fill=(23,25,37))
        _draw_wrapped_center_box(d,"ÚTVONAL → HELYZET → DÖNTÉS → PERFORMANCE",(foot[0]+16,foot[1]+5,foot[2]-16,foot[3]-5),start=19,minimum=12,max_lines=1,fill=MUTED)
        frames.append(img)
    return _save_gif(frames,[190,200,210,220,230,250,300,330,370,900],"route.gif")


def render_transport_state(player_name: str, title: str, *, accent, stage: int, total: int, score: int, reward: int, event: str, rating: str | None=None) -> BytesIO:
    img,d=_base(title,player_name,accent)
    if rating:
        _text_center(d,"MŰSZAK LEZÁRVA",168,_font(23,True),accent)
        box=(335,214,625,364)
        d.rounded_rectangle(box,radius=28,fill=PANEL_2,outline=accent,width=3)
        _text_center_box(d,rating,box,_font(82,True),GOLD)
        _draw_wrapped_center_box(d,event.upper(),(100,382,860,442),start=22,minimum=13,max_lines=2,fill=TEXT)
    else:
        _text_center(d,f"FUVAR {stage}/{total}",166,_font(22,True),accent)
        card=(125,210,835,390)
        d.rounded_rectangle(card,radius=24,fill=PANEL_2,outline=(74,78,102),width=2)
        _draw_wrapped_center_box(d,event.upper(),(card[0]+28,card[1]+24,card[2]-28,card[1]+104),start=28,minimum=15,max_lines=2,fill=TEXT)
        _draw_wrapped_center_box(d,"Válassz útvonalat az üzenet alatti gombokkal",(card[0]+24,card[1]+112,card[2]-24,card[3]-20),start=17,minimum=12,max_lines=1,fill=MUTED,bold=False)
    hud=(120,478,840,553)
    d.rounded_rectangle(hud,radius=18,fill=(23,25,37))
    hud_text=f"PERFORMANCE: {score}/100   •   RUN: ${reward:,}".replace(","," ")
    _draw_wrapped_center_box(d,hud_text,(hud[0]+18,hud[1]+6,hud[2]-18,hud[3]-6),start=20,minimum=12,max_lines=1,fill=MUTED)
    return _save_png(img,"transport_state.png")


def render_scenario_state(
    player_name: str,
    title: str,
    *,
    accent,
    stage: int,
    total: int,
    score: int,
    reward: int,
    scenario_title: str,
    prompt: str,
    choices: list[dict],
    seconds: int,
) -> BytesIO:
    img,d=_base(title,player_name,accent)
    _text_center(d,f"DÖNTÉSI HELYZET • {stage}/{total}",160,_font(20,True),accent)
    panel=(90,194,870,408)
    d.rounded_rectangle(panel,radius=24,fill=PANEL_2,outline=accent,width=2)
    _draw_wrapped_center_box(d,scenario_title.upper(),(panel[0]+26,panel[1]+12,panel[2]-26,panel[1]+64),start=27,minimum=16,max_lines=1,fill=TEXT)
    _draw_wrapped_center_box(d,str(prompt).strip(),(panel[0]+34,panel[1]+70,panel[2]-34,panel[1]+145),start=20,minimum=13,max_lines=3,fill=MUTED,bold=False,spacing=3)
    hint="Válassz az üzenet alatti gombokkal"
    _draw_wrapped_center_box(d,hint.upper(),(panel[0]+28,panel[1]+156,panel[2]-28,panel[3]-14),start=16,minimum=12,max_lines=1,fill=MUTED)
    timer=(315,422,645,468)
    d.rounded_rectangle(timer,radius=16,fill=(23,25,37),outline=GOLD,width=2)
    _text_center_box(d,f"{seconds} MP A DÖNTÉSRE",timer,_font(18,True),GOLD)
    hud=(120,486,840,552)
    d.rounded_rectangle(hud,radius=18,fill=(23,25,37),outline=(74,78,102),width=1)
    hud_text=f"PERFORMANCE: {score}/100   •   RUN: ${reward:,}".replace(","," ")
    _draw_wrapped_center_box(d,hud_text,(hud[0]+18,hud[1]+5,hud[2]-18,hud[3]-5),start=19,minimum=11,max_lines=1,fill=MUTED)
    return _save_png(img,"job_scenario.png")


def render_borsod_reveal_animation(player_name: str, board: list[str], index: int, reveal_token: str, attempts_left: int, loot_value: int) -> BytesIO:
    frames=[]
    for step, token in enumerate(("✦","✦",reveal_token,reveal_token)):
        temp=list(board); temp[index]=token
        img,d=_base("BORSODI LOPKODÁS",player_name,(240,165,50))
        headline="ÁTNÉZED A HELYET…" if step<2 else f"TALÁLAT: {_clean_borsod_text(reveal_token)}"
        headbox=(95,158,865,208)
        d.rounded_rectangle(headbox,radius=15,fill=(23,25,37),outline=(87,78,58),width=1)
        _draw_wrapped_center_box(d,headline.upper(),(headbox[0]+18,headbox[1]+5,headbox[2]-18,headbox[3]-5),start=21,minimum=13,max_lines=1,fill=GOLD if step<2 else TEXT)
        size=55; gap=8; total=5*size+4*gap; x0=(W-total)//2; y0=224
        for idx, cell in enumerate(temp[:25]):
            r,c=divmod(idx,5); x=x0+c*(size+gap); y=y0+r*(size+gap)
            active=idx==index
            fill=(62,54,35) if active else ((35,38,52) if cell=="?" else (48,51,66))
            outline=GOLD if active else ((90,94,116) if cell=="?" else (240,165,50))
            d.rounded_rectangle((x,y,x+size,y+size),radius=12,fill=fill,outline=outline,width=3 if active else 2)
            if cell != "?":
                _draw_borsod_token(d,cell,(x,y,x+size,y+size))
        hud=(145,542,815,582)
        d.rounded_rectangle(hud,radius=16,fill=(23,25,37))
        hud_text=f"KERESÉS: {attempts_left}   •   RUN LOOT: ${loot_value:,}".replace(","," ")
        _draw_wrapped_center_box(d,hud_text,(hud[0]+15,hud[1]+3,hud[2]-15,hud[3]-3),start=18,minimum=11,max_lines=1,fill=MUTED)
        frames.append(img)
    return _save_gif(frames,[260,300,520,1100],"borsod_reveal.gif")


def render_job_final(player_name: str, title: str, *, accent, rating: str, score: int, reward: int, mastery_level: int, mastery_xp: int) -> BytesIO:
    img,d=_base(title,player_name,accent)
    _text_center(d,"MŰSZAK LEZÁRVA",174,_font(23,True),accent)
    rating_box = JOB_UI.final_rating
    d.rounded_rectangle(rating_box,radius=28,fill=PANEL_2,outline=accent,width=3)
    _text_center_box(d,rating,rating_box,_font(82,True),GOLD)
    cards=[(95,JOB_UI.final_cards_y0,345,JOB_UI.final_cards_y1),(355,JOB_UI.final_cards_y0,605,JOB_UI.final_cards_y1),(615,JOB_UI.final_cards_y0,865,JOB_UI.final_cards_y1)]
    data=[("PERFORMANCE",f"{score}/100"),("KIFIZETÉS",f"${reward:,}".replace(","," ")),("MASTERY",f"LV.{mastery_level}  +{mastery_xp} XP")]
    for box,(label,value) in zip(cards,data):
        d.rounded_rectangle(box,radius=18,fill=(23,25,37),outline=(74,78,102),width=2)
        label_box=(box[0]+8,box[1]+10,box[2]-8,box[1]+42)
        value_box=(box[0]+8,box[1]+43,box[2]-8,box[3]-8)
        _text_center_box(d,label,label_box,_font(15,True),MUTED)
        vf=_fit(d,value,box[2]-box[0]-20,22,10)
        _text_center_box(d,value,value_box,vf,TEXT)
    _text_center(d,"YORU JOBS • aktív teljesítmény, nem AFK farm",JOB_UI.footer_y,_font(16,False),MUTED)
    return _save_png(img,"job_final.png")
