from __future__ import annotations

from io import BytesIO
import random

from PIL import Image, ImageDraw

from app.casino_quick_visuals import (
    BG, PANEL, PANEL_ALT, TEXT, MUTED, GOLD, GREEN, RED, BLUE,
    _font, _rr, _text_size, _fit_font, _gif, _png,
)

WIDTH = 960
HEIGHT = 640
CENTER_X = WIDTH / 2


def _clean_name(value: str | None, fallback: str) -> str:
    raw = " ".join(str(value or fallback).split()).strip() or fallback
    if len(raw) > 22:
        raw = raw[:21].rstrip() + "…"
    return raw.upper()


def _draw_centered(draw: ImageDraw.ImageDraw, center: tuple[float, float], text: str, font, fill) -> None:
    """Center by the actual glyph bounding box, not the font baseline.

    Pillow's anchor='mm' centers the text anchor, but some fonts still look vertically
    shifted because of ascenders/descenders. This helper centers the rendered glyph box
    itself around the requested point and is used for every PvP score/result/HUD value.
    """
    cx, cy = center
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    x = cx - (left + right) / 2
    y = cy - (top + bottom) / 2
    draw.text((x, y), text, font=font, fill=fill)


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
    lf = _fit_font(draw, left, 310, start=24, minimum=16, bold=True)
    rf = _fit_font(draw, right, 310, start=24, minimum=16, bold=True)

    _rr(draw, (54, 96, 404, 142), 18, (39, 37, 54), outline=BLUE, width=2)
    _rr(draw, (556, 96, 906, 142), 18, (39, 37, 54), outline=RED, width=2)
    _draw_centered(draw, (229, 119), left, lf, TEXT)
    _draw_centered(draw, (731, 119), right, rf, TEXT)
    _draw_centered(draw, (480, 119), "VS", _font(22, bold=True), GOLD)
    return image, draw


def _winner_banner(draw: ImageDraw.ImageDraw, winner_name: str | None, *, tie: bool = False) -> None:
    """Dedicated centered result row, physically separate from the game arena."""
    _rr(draw, (190, 482, 770, 535), 18, (39, 40, 54), outline=(74, 72, 95), width=2)
    if tie:
        text = "DÖNTETLEN"
        fill = GOLD
    else:
        text = f"{_clean_name(winner_name, 'WINNER')} NYERT"
        fill = GREEN
    wf = _fit_font(draw, text, 520, start=27, minimum=18, bold=True)
    _draw_centered(draw, (480, 508.5), text, wf, fill)


def _hud_card(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], label: str, value: str, *, value_fill) -> None:
    x1, y1, x2, y2 = box
    _rr(draw, box, 17, PANEL_ALT, outline=(74, 72, 95), width=2)
    cx = (x1 + x2) / 2
    _draw_centered(draw, (cx, y1 + 20), label, _font(14, bold=True), MUTED)
    vf = _fit_font(draw, value, x2 - x1 - 28, start=18, minimum=14, bold=True)
    _draw_centered(draw, (cx, y1 + 47), value, vf, value_fill)


def _footer(draw: ImageDraw.ImageDraw, stake: int, pot: int, phase: str) -> None:
    # Three visibly separate, exactly equal-width cards. This makes the column centers
    # obvious to the eye and prevents the old "one long row with random padding" look.
    cards = ((54, 548, 326, 622), (344, 548, 616, 622), (634, 548, 906, 622))
    _hud_card(draw, cards[0], "TÉT / FŐ", f"${stake:,}".replace(",", " "), value_fill=TEXT)
    _hud_card(draw, cards[1], "POT", f"${pot:,}".replace(",", " "), value_fill=GOLD)
    _hud_card(draw, cards[2], "ÁLLAPOT", str(phase), value_fill=TEXT)


def render_duel_challenge(game: str, left_name: str, right_name: str, stake: int) -> BytesIO:
    image, draw = _base(game, left_name, right_name)
    _rr(draw, (120, 175, 840, 470), 34, PANEL, outline=(83, 77, 112), width=3)
    icon = {"coinflip": "COINFLIP", "dice": "DICE", "rps": "RPS"}.get(game, game.upper())
    f = _fit_font(draw, icon, 620, start=64, minimum=38, bold=True)
    _draw_centered(draw, (480, 300), icon, f, TEXT)
    _draw_centered(draw, (480, 385), "CHALLENGE", _font(28, bold=True), GOLD)
    _footer(draw, stake, stake * 2, "ACCEPT?")
    return _png(image, "pvp_challenge.png")


def _coin_frame(left_name: str, right_name: str, stake: int, side: int, scale: float, phase: str, winner: str | None = None) -> Image.Image:
    image, draw = _base("COINFLIP", left_name, right_name)
    _rr(draw, (120, 165, 840, 470), 34, PANEL, outline=(83, 77, 112), width=3)
    cx, cy = 480, 318
    r = 128
    ry = max(12, int(r * max(.08, scale)))
    fill = GOLD if side == 0 else (178, 182, 194)
    draw.ellipse((cx-r, cy-ry, cx+r, cy+ry), fill=fill, outline=(255, 230, 150), width=8)
    if ry > 40:
        label = "YORU" if side else "PVP"
        lf = _font(max(20, int(38 * min(1, scale))), bold=True)
        _draw_centered(draw, (cx, cy), label, lf, (55, 56, 68))
    if winner:
        _winner_banner(draw, winner)
    _footer(draw, stake, stake * 2, phase)
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
    durations = [115] * (len(frames) - 7) + [140, 160, 190, 220, 260, 330, 850]
    return _gif(frames, durations, "pvp_coinflip.gif")


def render_pvp_coinflip(left_name: str, right_name: str, stake: int, winner_name: str) -> BytesIO:
    return _png(_coin_frame(left_name, right_name, stake, 0, 1.0, "RESULT", winner_name), "pvp_coinflip.png")


def _score_frame(game: str, left_name: str, right_name: str, stake: int, left_score: int, right_score: int, phase: str, winner_name: str | None = None) -> Image.Image:
    image, draw = _base(game, left_name, right_name)
    _rr(draw, (90, 175, 870, 470), 34, PANEL, outline=(83, 77, 112), width=3)

    score_y = 322
    for cx, score, accent in ((280, left_score, BLUE), (680, right_score, RED)):
        draw.ellipse((cx - 108, score_y - 108, cx + 108, score_y + 108), fill=(48, 49, 65), outline=accent, width=7)
        sf = _fit_font(draw, str(score), 150, start=76, minimum=50, bold=True)
        _draw_centered(draw, (cx, score_y), str(score), sf, TEXT)

    _draw_centered(draw, (480, score_y), "VS", _font(36, bold=True), GOLD)
    if winner_name:
        _winner_banner(draw, winner_name)
    _footer(draw, stake, stake * 2, phase)
    return image


def render_pvp_dice_animation(left_name: str, right_name: str, stake: int, left_score: int, right_score: int, winner_name: str) -> BytesIO:
    rng = random.Random((left_score << 8) ^ right_score ^ stake)
    frames = [_score_frame("DICE", left_name, right_name, stake, rng.randint(1, 100), rng.randint(1, 100), "ROLLING…") for _ in range(8)]
    frames.append(_score_frame("DICE", left_name, right_name, stake, left_score, right_score, "RESULT", winner_name))
    return _gif(frames, [125, 125, 135, 145, 165, 190, 230, 300, 900], "pvp_dice.gif")


def render_pvp_dice(left_name: str, right_name: str, stake: int, left_score: int, right_score: int, winner_name: str) -> BytesIO:
    return _png(_score_frame("DICE", left_name, right_name, stake, left_score, right_score, "RESULT", winner_name), "pvp_dice.png")


def _rps_symbol(choice: str | None) -> str:
    return {"rock": "ROCK", "paper": "PAPER", "scissors": "SCISSORS"}.get(str(choice or ""), "?")


def _rps_frame(left_name: str, right_name: str, stake: int, left_choice: str | None, right_choice: str | None, phase: str, countdown: str | None = None, winner_name: str | None = None) -> Image.Image:
    image, draw = _base("RPS", left_name, right_name)
    _rr(draw, (90, 175, 870, 470), 34, PANEL, outline=(83, 77, 112), width=3)

    for cx, choice, accent in ((280, left_choice, BLUE), (680, right_choice, RED)):
        box = (155 if cx == 280 else 555, 225, 405 if cx == 280 else 805, 420)
        _rr(draw, box, 26, (47, 48, 64), outline=accent, width=4)
        label = _rps_symbol(choice)
        f = _fit_font(draw, label, 205, start=40, minimum=24, bold=True)
        _draw_centered(draw, (cx, 322), label, f, TEXT if choice else MUTED)

    if countdown:
        _draw_centered(draw, (480, 322), countdown, _font(72, bold=True), GOLD)
    else:
        _draw_centered(draw, (480, 322), "VS", _font(34, bold=True), GOLD)

    if winner_name:
        _winner_banner(draw, winner_name, tie=winner_name == "TIE")
    _footer(draw, stake, stake * 2, phase)
    return image


def render_pvp_rps_wait(left_name: str, right_name: str, stake: int) -> BytesIO:
    return _png(_rps_frame(left_name, right_name, stake, None, None, "CHOOSE"), "pvp_rps_wait.png")


def render_pvp_rps_animation(left_name: str, right_name: str, stake: int, left_choice: str, right_choice: str, winner_name: str | None) -> BytesIO:
    final = winner_name or "TIE"
    frames = [
        _rps_frame(left_name, right_name, stake, None, None, "LOCKED IN", "3"),
        _rps_frame(left_name, right_name, stake, None, None, "LOCKED IN", "2"),
        _rps_frame(left_name, right_name, stake, None, None, "LOCKED IN", "1"),
        _rps_frame(left_name, right_name, stake, left_choice, right_choice, "REVEAL", None, final),
    ]
    return _gif(frames, [430, 430, 520, 1050], "pvp_rps.gif")


def render_pvp_rps(left_name: str, right_name: str, stake: int, left_choice: str, right_choice: str, winner_name: str | None) -> BytesIO:
    return _png(_rps_frame(left_name, right_name, stake, left_choice, right_choice, "RESULT", None, winner_name or "TIE"), "pvp_rps.png")
