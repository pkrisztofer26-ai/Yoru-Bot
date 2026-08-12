from __future__ import annotations

from io import BytesIO
import random

from PIL import Image, ImageDraw

from app.casino_quick_visuals import (
    BG, PANEL, PANEL_ALT, TEXT, MUTED, GOLD, GREEN, RED, PURPLE, WHITE, BLUE,
    HEADER_PURPLE, _font, _rr, _text_size, _fit_font, _gif, _png,
)

WIDTH = 960
HEIGHT = 640


def _clean_name(value: str | None, fallback: str) -> str:
    raw = " ".join(str(value or fallback).split()).strip() or fallback
    if len(raw) > 22:
        raw = raw[:21].rstrip() + "…"
    return raw.upper()


def _base(game: str, left_name: str, right_name: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)
    title = f"YORU PVP • {game.upper()}"
    tf = _fit_font(draw, title, 620, start=34, minimum=23, bold=True)
    draw.text((42, 24), title, font=tf, fill=TEXT)
    cf = _font(17, bold=True)
    casino = "YORU CASINO"
    cw, _ = _text_size(draw, casino, cf)
    draw.text((918 - cw, 37), casino, font=cf, fill=GOLD)
    draw.line((42, 78, 918, 78), fill=(56, 55, 75), width=2)

    left = _clean_name(left_name, "PLAYER 1")
    right = _clean_name(right_name, "PLAYER 2")
    lf = _fit_font(draw, left, 330, start=24, minimum=16, bold=True)
    rf = _fit_font(draw, right, 330, start=24, minimum=16, bold=True)
    lw, _ = _text_size(draw, left, lf)
    rw, _ = _text_size(draw, right, rf)
    _rr(draw, (54, 96, 404, 142), 18, (39, 37, 54), outline=BLUE, width=2)
    _rr(draw, (556, 96, 906, 142), 18, (39, 37, 54), outline=RED, width=2)
    draw.text((229 - lw / 2, 105), left, font=lf, fill=TEXT)
    draw.text((731 - rw / 2, 105), right, font=rf, fill=TEXT)
    vsf = _font(22, bold=True)
    vsw, _ = _text_size(draw, "VS", vsf)
    draw.text((480 - vsw / 2, 107), "VS", font=vsf, fill=GOLD)
    return image, draw


def _footer(draw: ImageDraw.ImageDraw, stake: int, pot: int, phase: str) -> None:
    _rr(draw, (70, 548, 890, 612), 20, PANEL_ALT, outline=(74, 72, 95), width=2)
    sf = _font(18, bold=True)
    draw.text((96, 565), f"TÉT / FŐ  ${stake:,}".replace(",", " "), font=sf, fill=MUTED)
    pot_text = f"POT  ${pot:,}".replace(",", " ")
    pw, _ = _text_size(draw, pot_text, sf)
    draw.text((480 - pw / 2, 565), pot_text, font=sf, fill=GOLD)
    pf = _font(17, bold=True)
    ph, _ = _text_size(draw, phase, pf)
    draw.text((865 - ph, 566), phase, font=pf, fill=TEXT)


def render_duel_challenge(game: str, left_name: str, right_name: str, stake: int) -> BytesIO:
    image, draw = _base(game, left_name, right_name)
    _rr(draw, (120, 180, 840, 515), 34, PANEL, outline=(83, 77, 112), width=3)
    icon = {"coinflip": "COINFLIP", "dice": "DICE", "rps": "RPS"}.get(game, game.upper())
    f = _fit_font(draw, icon, 620, start=64, minimum=38, bold=True)
    w, h = _text_size(draw, icon, f)
    draw.text((480 - w / 2, 280 - h / 2), icon, font=f, fill=TEXT)
    sub = "CHALLENGE"
    sf = _font(28, bold=True)
    sw, _ = _text_size(draw, sub, sf)
    draw.text((480 - sw / 2, 370), sub, font=sf, fill=GOLD)
    _footer(draw, stake, stake * 2, "ACCEPT?")
    return _png(image, "pvp_challenge.png")


def _coin_frame(left_name: str, right_name: str, stake: int, side: int, scale: float, phase: str, winner: str | None = None) -> Image.Image:
    image, draw = _base("COINFLIP", left_name, right_name)
    _rr(draw, (120, 165, 840, 525), 34, PANEL, outline=(83, 77, 112), width=3)
    cx, cy = 480, 342
    r = 138
    ry = max(12, int(r * max(.08, scale)))
    fill = GOLD if side == 0 else (178, 182, 194)
    draw.ellipse((cx-r, cy-ry, cx+r, cy+ry), fill=fill, outline=(255, 230, 150), width=8)
    if ry > 40:
        label = "YORU" if side else "PVP"
        lf = _font(max(20, int(38 * min(1, scale))), bold=True)
        lw, lh = _text_size(draw, label, lf)
        draw.text((cx-lw/2, cy-lh/2), label, font=lf, fill=(55,56,68))
    if winner:
        wf = _fit_font(draw, f"{_clean_name(winner, 'WINNER')} NYERT", 620, start=32, minimum=20, bold=True)
        ww, _ = _text_size(draw, f"{_clean_name(winner, 'WINNER')} NYERT", wf)
        draw.text((480-ww/2, 476), f"{_clean_name(winner, 'WINNER')} NYERT", font=wf, fill=GREEN)
    _footer(draw, stake, stake*2, phase)
    return image


def render_pvp_coinflip_animation(left_name: str, right_name: str, stake: int, winner_name: str) -> BytesIO:
    frames: list[Image.Image] = []
    scales = [1.0, .58, .18, .08, .22, .64, 1.0]
    side = 0
    for _ in range(3):
        for i, scale in enumerate(scales):
            if i == 4:
                side = 1 - side
            frames.append(_coin_frame(left_name, right_name, stake, side, scale, "FLIPPING…"))
    frames.append(_coin_frame(left_name, right_name, stake, side, 1.0, "FINAL", winner_name))
    durations = [115] * (len(frames)-7) + [140, 160, 190, 220, 260, 330, 850]
    return _gif(frames, durations, "pvp_coinflip.gif")


def render_pvp_coinflip(left_name: str, right_name: str, stake: int, winner_name: str) -> BytesIO:
    return _png(_coin_frame(left_name, right_name, stake, 0, 1.0, "RESULT", winner_name), "pvp_coinflip.png")


def _score_frame(game: str, left_name: str, right_name: str, stake: int, left_score: int, right_score: int, phase: str, winner_name: str | None = None) -> Image.Image:
    image, draw = _base(game, left_name, right_name)
    _rr(draw, (90, 175, 870, 525), 34, PANEL, outline=(83, 77, 112), width=3)
    for cx, score, accent in ((280, left_score, BLUE), (680, right_score, RED)):
        draw.ellipse((cx-112, 235, cx+112, 459), fill=(48,49,65), outline=accent, width=7)
        sf = _font(76, bold=True)
        sw, sh = _text_size(draw, str(score), sf)
        draw.text((cx-sw/2, 347-sh/2), str(score), font=sf, fill=TEXT)
    vf = _font(36, bold=True)
    vw, _ = _text_size(draw, "VS", vf)
    draw.text((480-vw/2, 330), "VS", font=vf, fill=GOLD)
    if winner_name:
        text = f"{_clean_name(winner_name,'WINNER')} NYERT"
        wf = _fit_font(draw, text, 600, start=27, minimum=18, bold=True)
        ww, _ = _text_size(draw, text, wf)
        draw.text((480-ww/2, 482), text, font=wf, fill=GREEN)
    _footer(draw, stake, stake*2, phase)
    return image


def render_pvp_dice_animation(left_name: str, right_name: str, stake: int, left_score: int, right_score: int, winner_name: str) -> BytesIO:
    rng = random.Random((left_score << 8) ^ right_score ^ stake)
    frames = [_score_frame("DICE", left_name, right_name, stake, rng.randint(1,100), rng.randint(1,100), "ROLLING…") for _ in range(8)]
    frames.append(_score_frame("DICE", left_name, right_name, stake, left_score, right_score, "RESULT", winner_name))
    return _gif(frames, [125,125,135,145,165,190,230,300,900], "pvp_dice.gif")


def render_pvp_dice(left_name: str, right_name: str, stake: int, left_score: int, right_score: int, winner_name: str) -> BytesIO:
    return _png(_score_frame("DICE", left_name, right_name, stake, left_score, right_score, "RESULT", winner_name), "pvp_dice.png")


def _rps_symbol(choice: str | None) -> str:
    return {"rock":"ROCK", "paper":"PAPER", "scissors":"SCISSORS"}.get(str(choice or ""), "?")


def _rps_frame(left_name: str, right_name: str, stake: int, left_choice: str | None, right_choice: str | None, phase: str, countdown: str | None = None, winner_name: str | None = None) -> Image.Image:
    image, draw = _base("RPS", left_name, right_name)
    _rr(draw, (90, 175, 870, 525), 34, PANEL, outline=(83,77,112), width=3)
    for cx, choice, accent in ((280,left_choice,BLUE),(680,right_choice,RED)):
        _rr(draw, (155 if cx==280 else 555, 245, 405 if cx==280 else 805, 440), 26, (47,48,64), outline=accent, width=4)
        label = _rps_symbol(choice)
        f = _fit_font(draw, label, 205, start=40, minimum=24, bold=True)
        w,h = _text_size(draw,label,f)
        draw.text((cx-w/2, 342-h/2), label, font=f, fill=TEXT if choice else MUTED)
    if countdown:
        f=_font(72,bold=True); w,h=_text_size(draw,countdown,f)
        draw.text((480-w/2,342-h/2),countdown,font=f,fill=GOLD)
    else:
        f=_font(34,bold=True); w,_=_text_size(draw,"VS",f); draw.text((480-w/2,325),"VS",font=f,fill=GOLD)
    if winner_name:
        text = "DÖNTETLEN" if winner_name == "TIE" else f"{_clean_name(winner_name,'WINNER')} NYERT"
        wf=_fit_font(draw,text,600,start=27,minimum=18,bold=True); ww,_=_text_size(draw,text,wf)
        draw.text((480-ww/2,482),text,font=wf,fill=GOLD if winner_name=="TIE" else GREEN)
    _footer(draw,stake,stake*2,phase)
    return image


def render_pvp_rps_wait(left_name: str, right_name: str, stake: int) -> BytesIO:
    return _png(_rps_frame(left_name,right_name,stake,None,None,"CHOOSE"),"pvp_rps_wait.png")


def render_pvp_rps_animation(left_name: str, right_name: str, stake: int, left_choice: str, right_choice: str, winner_name: str | None) -> BytesIO:
    final = winner_name or "TIE"
    frames = [
        _rps_frame(left_name,right_name,stake,None,None,"LOCKED IN","3"),
        _rps_frame(left_name,right_name,stake,None,None,"LOCKED IN","2"),
        _rps_frame(left_name,right_name,stake,None,None,"LOCKED IN","1"),
        _rps_frame(left_name,right_name,stake,left_choice,right_choice,"REVEAL",None,final),
    ]
    return _gif(frames,[430,430,520,1050],"pvp_rps.gif")


def render_pvp_rps(left_name: str, right_name: str, stake: int, left_choice: str, right_choice: str, winner_name: str | None) -> BytesIO:
    return _png(_rps_frame(left_name,right_name,stake,left_choice,right_choice,"RESULT",None,winner_name or "TIE"),"pvp_rps.png")
