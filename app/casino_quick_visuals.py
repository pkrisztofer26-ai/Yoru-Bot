from __future__ import annotations

from io import BytesIO
import math
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont

BG = (20, 20, 29)
PANEL = (34, 35, 48)
PANEL_ALT = (45, 46, 63)
TEXT = (244, 244, 248)
MUTED = (169, 171, 188)
GOLD = (244, 191, 72)
GREEN = (43, 176, 113)
RED = (210, 57, 75)
PURPLE = (118, 82, 219)
WHITE = (250, 250, 250)
BLUE = (69, 139, 240)
HEADER_PURPLE = (91, 76, 128)


def _font(size: int, *, bold: bool = False):
    candidates = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _owner(player_name: str | None) -> str:
    raw = " ".join(str(player_name or "PLAYER").split()).strip() or "PLAYER"
    if len(raw) > 24:
        raw = raw[:23].rstrip() + "…"
    return f"{raw.upper()}'S GAME"


def _png(image: Image.Image, name: str) -> BytesIO:
    fp = BytesIO()
    image.save(fp, format="PNG", optimize=False, compress_level=1)
    fp.seek(0)
    fp.name = name
    return fp


def _gif(frames: list[Image.Image], durations: list[int], name: str) -> BytesIO:
    fp = BytesIO()
    pal = [frame.convert("P", palette=Image.Palette.ADAPTIVE, colors=128) for frame in frames]
    pal[0].save(
        fp,
        format="GIF",
        save_all=True,
        append_images=pal[1:],
        duration=durations,
        disposal=2,
        optimize=False,
        loop=0,
    )
    fp.seek(0)
    fp.name = name
    return fp


def _rr(draw: ImageDraw.ImageDraw, box, radius=22, fill=PANEL, outline=None, width=2):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def _text_size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def _center_text(draw: ImageDraw.ImageDraw, text: str, y: int, *, font, fill=TEXT, width: int = 960) -> None:
    tw, _ = _text_size(draw, text, font)
    draw.text(((width - tw) / 2, y), text, font=font, fill=fill)


def _fit_font(draw: ImageDraw.ImageDraw, text: str, max_width: int, *, start: int, minimum: int = 16, bold: bool = True):
    size = start
    while size > minimum:
        font = _font(size, bold=bold)
        if _text_size(draw, text, font)[0] <= max_width:
            return font
        size -= 1
    return _font(minimum, bold=bold)


def _base(title: str, player_name: str | None, *, subtitle: str = "YORU CASINO", height: int = 640) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    """Shared mobile-safe Casino header.

    Row 1 is reserved for game title + Yoru branding. Row 2 is exclusively the
    player's shareable ownership badge, so long titles can never collide with it.
    """
    image = Image.new("RGB", (960, height), BG)
    draw = ImageDraw.Draw(image)

    title_font = _fit_font(draw, title, 610, start=36, minimum=25, bold=True)
    draw.text((42, 24), title, font=title_font, fill=TEXT)

    casino_font = _font(17, bold=True)
    cw, _ = _text_size(draw, subtitle, casino_font)
    draw.text((918 - cw, 37), subtitle, font=casino_font, fill=GOLD)

    # Thin separator makes the header feel deliberate rather than like floating text.
    draw.line((42, 78, 918, 78), fill=(56, 55, 75), width=2)

    label = _owner(player_name)
    owner_font = _fit_font(draw, label, 500, start=21, minimum=16, bold=True)
    lw, lh = _text_size(draw, label, owner_font)
    badge_w = min(560, max(250, lw + 52))
    x1 = (960 - badge_w) / 2
    _rr(draw, (x1, 90, x1 + badge_w, 128), 18, (39, 37, 54), outline=HEADER_PURPLE, width=2)
    draw.text(((960 - lw) / 2, 97), label, font=owner_font, fill=(215, 209, 232))
    return image, draw


# ---------------------------------------------------------------- Coinflip

def _coin_image(
    side: str | None,
    player_name: str | None,
    phase: str,
    *,
    flip_scale: float = 1.0,
    vertical_offset: int = 0,
) -> Image.Image:
    image, draw = _base("YORU COINFLIP", player_name, height=640)
    cx, cy = 480, 360 + vertical_offset
    _rr(draw, (130, 148, 830, 568), 36, PANEL, outline=(83, 77, 112), width=3)

    r = 150
    ry = max(13, int(r * max(0.08, flip_scale)))
    fill = GOLD if side == "fej" else ((174, 178, 191) if side == "írás" else (102, 94, 132))
    draw.ellipse((cx - r, cy - ry, cx + r, cy + ry), fill=fill, outline=(255, 230, 150), width=8)
    if ry > 40:
        draw.ellipse(
            (cx - r + 18, cy - ry + 18, cx + r - 18, cy + ry - 18),
            outline=(126, 103, 55) if side == "fej" else (100, 102, 116),
            width=4,
        )

        if side == "fej":
            head_r = min(48, max(18, int(48 * flip_scale)))
            draw.ellipse((cx - head_r, cy - head_r, cx + head_r, cy + head_r), fill=(235, 211, 155), outline=(95, 75, 45), width=4)
            face = "FEJ"
        elif side == "írás":
            face = "ÍRÁS"
            face_font = _font(max(19, int(40 * min(1, flip_scale))), bold=True)
            tw, th = _text_size(draw, "YORU", face_font)
            draw.text((cx - tw / 2, cy - th / 2 - 3), "YORU", font=face_font, fill=(54, 55, 67))
        else:
            face = "?"
    else:
        face = ""

    # Result label belongs below the coin, not on top of it.
    if face and phase == "RESULT":
        result_font = _font(42, bold=True)
        tw, _ = _text_size(draw, face, result_font)
        draw.text((cx - tw / 2, 520), face, font=result_font, fill=TEXT)

    phase_font = _font(18, bold=True)
    pw, _ = _text_size(draw, phase, phase_font)
    draw.text((480 - pw / 2, 585), phase, font=phase_font, fill=GOLD if phase == "RESULT" else MUTED)
    return image


def render_coinflip_animation(result_side: str, *, player_name: str | None = None) -> BytesIO:
    # Real flip illusion: the coin compresses to an edge, changes face, then opens.
    # Three full flips + a slower final reveal.
    result_side = str(result_side).lower()
    other = "írás" if result_side == "fej" else "fej"
    scales = [1.0, 0.62, 0.20, 0.08, 0.25, 0.70, 1.0]
    frames: list[Image.Image] = []
    for cycle in range(3):
        a, b = ("fej", "írás") if cycle % 2 == 0 else ("írás", "fej")
        for i, scale in enumerate(scales[:-1]):
            side = a if i < 3 else b
            lift = -int(24 * math.sin((i / max(1, len(scales) - 2)) * math.pi))
            frames.append(_coin_image(side, player_name, "FLIPPING…", flip_scale=scale, vertical_offset=lift))
    # Final half turn resolves deterministically to the actual result.
    for scale, side in [(0.55, other), (0.12, other), (0.28, result_side), (0.70, result_side), (1.0, result_side)]:
        frames.append(_coin_image(side, player_name, "FLIPPING…", flip_scale=scale, vertical_offset=-10))
    frames.append(_coin_image(result_side, player_name, "RESULT", flip_scale=1.0))
    durations = [95] * (len(frames) - 6) + [120, 145, 170, 210, 260, 900]
    return _gif(frames, durations, "coinflip.gif")


def render_coinflip(result_side: str, *, player_name: str | None = None) -> BytesIO:
    return _png(_coin_image(result_side, player_name, "RESULT"), "coinflip.png")


# ---------------------------------------------------------------- Dice

def _draw_die(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], value: int, *, active=True) -> None:
    x1, y1, x2, y2 = box
    _rr(draw, box, 30, (246, 246, 249) if active else (96, 98, 112), outline=(185, 185, 196), width=4)
    cx = (x1 + x2) // 2
    cy = (y1 + y2) // 2
    dx = (x2 - x1) // 4
    dy = (y2 - y1) // 4
    r = max(8, (x2 - x1) // 22)
    spots = {
        1: [(0, 0)],
        2: [(-1, -1), (1, 1)],
        3: [(-1, -1), (0, 0), (1, 1)],
        4: [(-1, -1), (1, -1), (-1, 1), (1, 1)],
        5: [(-1, -1), (1, -1), (0, 0), (-1, 1), (1, 1)],
        6: [(-1, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (1, 1)],
    }
    for ox, oy in spots.get(int(value), []):
        px = cx + ox * dx
        py = cy + oy * dy
        draw.ellipse((px - r, py - r, px + r, py + r), fill=(36, 37, 44) if active else (170, 172, 185))


def _dice_image(values: tuple[int, ...], player_name: str | None, phase: str, mode_label: str, *, jitter: tuple[int, int] = (0, 0)) -> Image.Image:
    image, draw = _base("YORU DICE", player_name, height=640)
    _rr(draw, (110, 148, 850, 555), 36, PANEL, outline=(83, 77, 112), width=3)
    jx, jy = jitter
    if len(values) == 1:
        _draw_die(draw, (330 + jx, 205 + jy, 630 + jx, 505 + jy), values[0])
    else:
        _draw_die(draw, (185 + jx, 220 + jy, 455 + jx, 490 + jy), values[0])
        _draw_die(draw, (505 - jx, 220 - jy, 775 - jx, 490 - jy), values[1])

    mode_font = _font(17, bold=True)
    mw, _ = _text_size(draw, mode_label, mode_font)
    draw.text((820 - mw, 166), mode_label, font=mode_font, fill=GOLD)
    _center_text(draw, phase, 585, font=_font(18, bold=True), fill=GOLD if phase == "RESULT" else MUTED)
    return image


def render_dice_animation(values: tuple[int, ...], *, player_name: str | None = None, mode_label: str = "DICE") -> BytesIO:
    frames: list[Image.Image] = []
    # Dice bounce around slightly while values rapidly change, then settle.
    jitters = [(-18, -8), (15, 9), (-10, 13), (12, -11), (-6, 5), (4, -3), (0, 0)]
    for i, jitter in enumerate(jitters):
        if i == len(jitters) - 1:
            vals = values
        else:
            vals = tuple((((i + 1) * 5 + j * 3) % 6) + 1 for j in range(len(values)))
        frames.append(_dice_image(vals, player_name, "ROLLING…" if i < len(jitters) - 1 else "RESULT", mode_label, jitter=jitter))
    return _gif(frames, [125, 130, 140, 155, 180, 230, 900], "dice.gif")


def render_dice(values: tuple[int, ...], *, player_name: str | None = None, mode_label: str = "DICE") -> BytesIO:
    return _png(_dice_image(values, player_name, "RESULT", mode_label), "dice.png")


# ---------------------------------------------------------------- RPS

def _draw_rps_shape(draw: ImageDraw.ImageDraw, center: tuple[int, int], choice: str, *, accent) -> None:
    cx, cy = center
    if choice == "rock":
        pts = [(cx - 90, cy + 50), (cx - 110, cy - 20), (cx - 65, cy - 90), (cx + 25, cy - 115), (cx + 100, cy - 55), (cx + 95, cy + 40), (cx + 35, cy + 100), (cx - 50, cy + 95)]
        draw.polygon(pts, fill=accent, outline=WHITE)
    elif choice == "paper":
        _rr(draw, (cx - 88, cy - 120, cx + 88, cy + 120), 18, (236, 236, 242), outline=accent, width=6)
        for off in (-50, -15, 20, 55):
            draw.line((cx - 55, cy + off, cx + 55, cy + off), fill=(150, 152, 165), width=4)
    else:
        draw.line((cx - 85, cy + 85, cx + 75, cy - 85), fill=accent, width=26)
        draw.line((cx - 75, cy - 85, cx + 85, cy + 85), fill=accent, width=26)
        draw.ellipse((cx - 105, cy + 55, cx - 45, cy + 115), outline=WHITE, width=8)
        draw.ellipse((cx + 45, cy + 55, cx + 105, cy + 115), outline=WHITE, width=8)


def _rps_image(player: str | None, bot: str | None, player_name: str | None, phase: str, *, countdown: str | None = None) -> Image.Image:
    image, draw = _base("YORU ROCK PAPER SCISSORS", player_name, height=640)
    _rr(draw, (55, 148, 905, 555), 36, PANEL, outline=(83, 77, 112), width=3)
    draw.text((175, 177), "YOU", font=_font(25, bold=True), fill=TEXT)
    draw.text((690, 177), "YORU", font=_font(25, bold=True), fill=TEXT)

    if player:
        _draw_rps_shape(draw, (235, 365), player, accent=BLUE)
    else:
        draw.text((210, 315), "?", font=_font(100, bold=True), fill=MUTED)
    if bot:
        _draw_rps_shape(draw, (725, 365), bot, accent=PURPLE)
    else:
        draw.text((700, 315), "?", font=_font(100, bold=True), fill=MUTED)

    if countdown:
        font = _font(78, bold=True)
        tw, _ = _text_size(draw, countdown, font)
        draw.text((480 - tw / 2, 315), countdown, font=font, fill=GOLD)
    else:
        draw.text((446, 336), "VS", font=_font(42, bold=True), fill=GOLD)
    _center_text(draw, phase, 585, font=_font(18, bold=True), fill=GOLD if phase == "REVEAL" else MUTED)
    return image


def render_rps_animation(player: str, bot: str, *, player_name: str | None = None) -> BytesIO:
    # Cleaner suspense: player's pick is locked, Yoru stays hidden through 3-2-1.
    frames = [
        _rps_image(player, None, player_name, "LOCKED IN", countdown="3"),
        _rps_image(player, None, player_name, "LOCKED IN", countdown="2"),
        _rps_image(player, None, player_name, "LOCKED IN", countdown="1"),
        _rps_image(player, None, player_name, "REVEALING…", countdown=None),
        _rps_image(player, bot, player_name, "REVEAL"),
    ]
    return _gif(frames, [420, 420, 500, 260, 950], "rps.gif")


def render_rps(player: str, bot: str, *, player_name: str | None = None) -> BytesIO:
    return _png(_rps_image(player, bot, player_name, "REVEAL"), "rps.png")


# ---------------------------------------------------------------- High / Low
CARD_LABELS = {2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8", 9: "9", 10: "10", 11: "J", 12: "Q", 13: "K", 14: "A"}


def _draw_card(draw: ImageDraw.ImageDraw, box, rank: int | None, *, hidden=False, accent=RED):
    x1, y1, x2, y2 = box
    _rr(draw, box, 24, (245, 245, 248) if not hidden else (57, 48, 78), outline=(190, 190, 200), width=4)
    if hidden or rank is None:
        for y in range(y1 + 20, y2 - 10, 18):
            draw.line((x1 + 18, y, x2 - 18, y), fill=(118, 104, 150), width=5)
        label = "YORU"
        lf = _font(30, bold=True)
        tw, th = _text_size(draw, label, lf)
        draw.text(((x1 + x2 - tw) / 2, (y1 + y2 - th) / 2), label, font=lf, fill=TEXT)
        return
    label = CARD_LABELS[int(rank)]
    font = _font(72, bold=True)
    tw, th = _text_size(draw, label, font)
    draw.text(((x1 + x2 - tw) / 2, (y1 + y2 - th) / 2 - 10), label, font=font, fill=accent)
    draw.text((x1 + 18, y1 + 12), label, font=_font(26, bold=True), fill=accent)
    draw.text((x2 - 45, y2 - 44), label, font=_font(26, bold=True), fill=accent)


def _highlow_image(
    current: int,
    next_rank: int | None,
    *,
    player_name: str | None,
    phase: str,
    multiplier: float,
    streak: int,
    reveal=True,
    slide_x: int = 0,
) -> Image.Image:
    image, draw = _base("YORU HIGH / LOW", player_name, height=680)
    _rr(draw, (75, 148, 885, 590), 36, PANEL, outline=(83, 77, 112), width=3)
    _draw_card(draw, (190, 205, 410, 535), current, accent=RED)
    _draw_card(draw, (550 + slide_x, 205, 770 + slide_x, 535), next_rank if reveal else None, hidden=not reveal, accent=BLUE)
    draw.text((452, 330), "→", font=_font(72, bold=True), fill=GOLD)

    draw.text((100, 615), f"STREAK  {streak}", font=_font(20, bold=True), fill=MUTED)
    mult = f"x{multiplier:.2f}"
    mw, _ = _text_size(draw, mult, _font(30, bold=True))
    draw.text((860 - mw, 608), mult, font=_font(30, bold=True), fill=GOLD)
    _center_text(draw, phase, 620, font=_font(18, bold=True), fill=TEXT)
    return image


def render_highlow(current: int, next_rank: int | None = None, *, player_name: str | None = None, phase: str = "CHOOSE", multiplier: float = 1.0, streak: int = 0, reveal=True) -> BytesIO:
    return _png(_highlow_image(current, next_rank, player_name=player_name, phase=phase, multiplier=multiplier, streak=streak, reveal=reveal), "highlow.png")


def render_highlow_animation(current: int, next_rank: int, *, player_name: str | None = None, multiplier: float = 1.0, streak: int = 0) -> BytesIO:
    # Card slides in from the right while face-down, then flips/reveals.
    frames = [
        _highlow_image(current, None, player_name=player_name, phase="DRAWING…", multiplier=multiplier, streak=streak, reveal=False, slide_x=220),
        _highlow_image(current, None, player_name=player_name, phase="DRAWING…", multiplier=multiplier, streak=streak, reveal=False, slide_x=140),
        _highlow_image(current, None, player_name=player_name, phase="DRAWING…", multiplier=multiplier, streak=streak, reveal=False, slide_x=70),
        _highlow_image(current, None, player_name=player_name, phase="DRAWING…", multiplier=multiplier, streak=streak, reveal=False, slide_x=0),
        _highlow_image(current, next_rank, player_name=player_name, phase="REVEAL", multiplier=multiplier, streak=streak, reveal=True, slide_x=0),
    ]
    return _gif(frames, [160, 170, 190, 300, 950], "highlow.gif")


# ---------------------------------------------------------------- Chicken Fight

def _chicken_image(
    player_hp: int,
    opponent_hp: int,
    opponent: str,
    *,
    player_name: str | None,
    phase: str,
    event: str = "",
    player_shift: int = 0,
    opponent_shift: int = 0,
    flash: str | None = None,
) -> Image.Image:
    image, draw = _base("YORU CHICKEN FIGHT", player_name, height=690)
    _rr(draw, (55, 148, 905, 600), 36, PANEL, outline=(83, 77, 112), width=3)

    def chicken(cx, cy, flip, accent):
        draw.ellipse((cx - 80, cy - 65, cx + 80, cy + 65), fill=(235, 220, 187), outline=accent, width=5)
        hx = cx + 65 * (-1 if flip else 1)
        draw.ellipse((hx - 30, cy - 85, hx + 30, cy - 25), fill=(245, 228, 190), outline=accent, width=4)
        beakx = hx + 38 * (-1 if flip else 1)
        draw.polygon([(hx, cy - 55), (beakx, cy - 42), (hx, cy - 30)], fill=GOLD)
        draw.ellipse((hx - 8, cy - 62, hx, cy - 54), fill=(30, 30, 36))
        draw.polygon([(hx - 18, cy - 86), (hx, cy - 112), (hx + 16, cy - 86)], fill=RED)

    p_cx = 245 + player_shift
    o_cx = 715 + opponent_shift
    chicken(p_cx, 355, False, BLUE)
    chicken(o_cx, 355, True, RED)

    # Clear labels live in their own row; opponent text is fitted instead of clipped.
    left_label = "YOUR CHICKEN"
    draw.text((145, 180), left_label, font=_font(23, bold=True), fill=TEXT)
    opp = str(opponent or "OPPONENT").upper()
    opp_font = _fit_font(draw, opp, 245, start=23, minimum=16, bold=True)
    ow, _ = _text_size(draw, opp, opp_font)
    draw.text((715 - ow / 2, 180), opp, font=opp_font, fill=TEXT)

    def hpbar(x, y, hp, accent):
        _rr(draw, (x, y, x + 260, y + 28), 14, (55, 56, 67), outline=(86, 87, 100), width=2)
        w = int(256 * max(0, min(100, hp)) / 100)
        if w > 1:
            _rr(draw, (x + 2, y + 2, x + 2 + w, y + 26), 12, accent, width=0)
        text = f"{hp}/100"
        tw, _ = _text_size(draw, text, _font(18, bold=True))
        draw.text((x + 130 - tw / 2, y + 35), text, font=_font(18, bold=True), fill=TEXT)

    hpbar(115, 485, player_hp, GREEN if player_hp > 30 else RED)
    hpbar(585, 485, opponent_hp, GREEN if opponent_hp > 30 else RED)

    if flash == "player":
        draw.ellipse((p_cx - 110, 250, p_cx + 110, 465), outline=(255, 220, 110), width=8)
    elif flash == "opponent":
        draw.ellipse((o_cx - 110, 250, o_cx + 110, 465), outline=(255, 220, 110), width=8)

    if event:
        event_font = _fit_font(draw, event, 650, start=23, minimum=17, bold=True)
        ew, _ = _text_size(draw, event, event_font)
        draw.text(((960 - ew) / 2, 560), event, font=event_font, fill=GOLD)
    _center_text(draw, phase, 635, font=_font(18, bold=True), fill=GOLD if phase == "RESULT" else MUTED)
    return image


def render_chicken_animation(frames_data: Iterable[tuple[int, int, str]], *, opponent: str, player_name: str | None = None) -> BytesIO:
    data = list(frames_data)
    frames: list[Image.Image] = []
    prev_php = 100
    prev_ohp = 100
    for i, (php, ohp, event) in enumerate(data):
        # Add an anticipation/attack frame before each HP state so it feels like a fight,
        # not a scoreboard whose numbers simply change.
        opponent_took_hit = ohp < prev_ohp
        player_took_hit = php < prev_php
        if opponent_took_hit:
            frames.append(_chicken_image(prev_php, prev_ohp, opponent, player_name=player_name, phase="ATTACK!", event=event, player_shift=55, opponent_shift=0))
            frames.append(_chicken_image(php, ohp, opponent, player_name=player_name, phase="HIT!", event=event, opponent_shift=22, flash="opponent"))
        elif player_took_hit:
            frames.append(_chicken_image(prev_php, prev_ohp, opponent, player_name=player_name, phase="ATTACK!", event=event, opponent_shift=-55, player_shift=0))
            frames.append(_chicken_image(php, ohp, opponent, player_name=player_name, phase="HIT!", event=event, player_shift=-22, flash="player"))
        else:
            frames.append(_chicken_image(php, ohp, opponent, player_name=player_name, phase="FIGHTING…", event=event))
        prev_php, prev_ohp = php, ohp

    if not frames:
        frames.append(_chicken_image(100, 100, opponent, player_name=player_name, phase="FIGHTING…"))
    # The final GIF frame is still animated-phase only; Discord swaps to a static PNG after settlement.
    durations = [220] * max(0, len(frames) - 2) + ([300, 650] if len(frames) >= 2 else [650])
    return _gif(frames, durations, "chicken.gif")


def render_chicken(player_hp: int, opponent_hp: int, *, opponent: str, event: str, player_name: str | None = None) -> BytesIO:
    return _png(_chicken_image(player_hp, opponent_hp, opponent, player_name=player_name, phase="RESULT", event=event), "chicken.png")
