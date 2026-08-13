from __future__ import annotations

from io import BytesIO
import math
from pathlib import Path
from typing import Iterable
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from app.casino_expansion import (
    CANDY_COLS,
    CANDY_ROWS,
    CANDY_SYMBOLS,
    MINES_COLS,
    MINES_ROWS,
    PLINKO_ROWS,
    PLINKO_MULTIPLIERS,
    ChickenRoadState,
    CandyRushResult,
    MinesState,
    PlinkoResult,
    chicken_multiplier,
)
from app.casino_ui_framework import (
    CASINO_BG, CASINO_PANEL, CASINO_PANEL_SOFT, CASINO_BORDER, CASINO_TEXT, CASINO_MUTED,
    CASINO_ACCENT, CASINO_ACCENT_SOFT, CASINO_MAGENTA, CASINO_GREEN, CASINO_RED,
    CasinoVisualStats, compact_amount,
)


W, H = 960, 640
BG = (17, 18, 27)
PANEL = (31, 33, 47)
PANEL_2 = (41, 44, 61)
TEXT = (246, 247, 252)
MUTED = (164, 169, 190)
GOLD = (247, 194, 70)
PURPLE = (119, 83, 235)
GREEN = (67, 205, 139)
RED = (235, 82, 91)
BLUE = (82, 132, 255)


@lru_cache(maxsize=128)
def _font(size: int, bold: bool = False):
    paths = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    )
    for path in paths:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _measure(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int, tuple[int, int, int, int]]:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1], box


def _center_box(draw: ImageDraw.ImageDraw, text: str, box: tuple[int, int, int, int], *, size: int, minimum: int = 12, fill=TEXT, bold=True):
    x0, y0, x1, y1 = box
    width = x1 - x0
    height = y1 - y0
    chosen = _font(minimum, bold)
    for current in range(size, minimum - 1, -1):
        font = _font(current, bold)
        tw, th, bounds = _measure(draw, text, font)
        if tw <= width and th <= height:
            chosen = font
            break
    tw, th, bounds = _measure(draw, text, chosen)
    tx = x0 + (width - tw) / 2 - bounds[0]
    ty = y0 + (height - th) / 2 - bounds[1]
    draw.text((tx, ty), text, font=chosen, fill=fill)


def _owner(name: str | None) -> str:
    raw = " ".join(str(name or "PLAYER").split()).strip() or "PLAYER"
    if len(raw) > 24:
        raw = raw[:23].rstrip() + "…"
    return f"{raw.upper()}'S GAME"


def _base(title: str, player_name: str | None, accent=PURPLE) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((26, 24, W - 26, H - 24), radius=28, fill=PANEL, outline=accent, width=3)
    _center_box(draw, title.upper(), (48, 38, 650, 91), size=37, minimum=22, fill=TEXT)
    _center_box(draw, "YORU CASINO", (735, 43, 906, 83), size=18, minimum=14, fill=accent)
    draw.line((52, 104, 908, 104), fill=(72, 74, 95), width=2)
    label = _owner(player_name)
    _center_box(draw, label, (170, 116, 790, 153), size=20, minimum=14, fill=MUTED)
    return image, draw


def _png(image: Image.Image, name: str) -> BytesIO:
    fp = BytesIO(); fp.name = name
    image.save(fp, format="PNG", optimize=False, compress_level=1); fp.seek(0)
    return fp


def _gif(
    frames: list[Image.Image],
    durations: list[int],
    name: str,
    *,
    loop: int | None = 0,
    colors: int = 128,
    shared_palette: bool = False,
    disposal: int = 2,
) -> BytesIO:
    fp = BytesIO(); fp.name = name
    color_count = max(32, min(256, int(colors)))
    if shared_palette and frames:
        first = frames[0].convert("P", palette=Image.Palette.ADAPTIVE, colors=color_count)
        pal = [first]
        pal.extend(frame.quantize(palette=first, dither=Image.Dither.NONE) for frame in frames[1:])
    else:
        pal = [frame.convert("P", palette=Image.Palette.ADAPTIVE, colors=color_count) for frame in frames]
    kwargs = dict(format="GIF", save_all=True, append_images=pal[1:], duration=durations, disposal=max(0, min(3, int(disposal))), optimize=False)
    # Omitting the Netscape loop extension makes the animation play once.
    # loop=0 is infinite and caused the visible Plinko restart at the finish.
    if loop is not None:
        kwargs["loop"] = int(loop)
    pal[0].save(fp, **kwargs)
    fp.seek(0)
    return fp


# ---------------------------------------------------------------- Mines


def _mines_image(state: MinesState, player_name: str | None, *, phase: str = "VÁLASSZ MEZŐT", flash: int | None = None, reveal_all=False, cashout_multiplier: float | None = None) -> Image.Image:
    image, draw = _base("MINES", player_name, BLUE)
    _center_box(draw, phase, (100, 162, 860, 202), size=22, minimum=14, fill=GOLD if state.exploded is None else RED)
    cell = 75; gap = 10
    total_w = MINES_COLS * cell + (MINES_COLS - 1) * gap
    total_h = MINES_ROWS * cell + (MINES_ROWS - 1) * gap
    sx = (W - total_w) // 2; sy = 218
    for index in range(MINES_ROWS * MINES_COLS):
        row, col = divmod(index, MINES_COLS)
        x = sx + col * (cell + gap); y = sy + row * (cell + gap)
        revealed = index in state.revealed or reveal_all
        is_mine = index in state.mines
        active = index == flash
        fill = (62, 54, 39) if active else ((55, 57, 73) if revealed else (37, 40, 55))
        outline = GOLD if active else ((RED if revealed and is_mine else (GREEN if revealed else (83, 87, 111))))
        draw.rounded_rectangle((x, y, x + cell, y + cell), radius=16, fill=fill, outline=outline, width=4 if active else 2)
        if revealed:
            if is_mine:
                cx, cy = x + cell // 2, y + cell // 2
                draw.ellipse((cx - 20, cy - 20, cx + 20, cy + 20), fill=RED)
                for angle in range(0, 360, 45):
                    rad = math.radians(angle)
                    draw.line((cx + math.cos(rad)*22, cy + math.sin(rad)*22, cx + math.cos(rad)*31, cy + math.sin(rad)*31), fill=RED, width=4)
            else:
                _center_box(draw, "✓", (x + 8, y + 6, x + cell - 8, y + cell - 6), size=38, minimum=24, fill=GREEN)
        else:
            _center_box(draw, str(index + 1), (x + 8, y + 6, x + cell - 8, y + cell - 6), size=19, minimum=13, fill=MUTED)
    hud=(128, 558, 832, 606)
    draw.rounded_rectangle(hud, radius=15, fill=(23,25,37))
    shown_mult = state.multiplier if cashout_multiplier is None else float(cashout_multiplier)
    _center_box(draw, f"BOMBÁK: {state.mine_count}   •   SAFE: {state.safe_reveals}   •   CASHOUT: x{shown_mult:.2f}", (hud[0]+10,hud[1]+4,hud[2]-10,hud[3]-4), size=18, minimum=12, fill=MUTED)
    return image


def render_mines(state: MinesState, *, player_name: str | None = None, reveal_all: bool = False, phase: str = "VÁLASSZ MEZŐT", cashout_multiplier: float | None = None) -> BytesIO:
    return _png(_mines_image(state, player_name, phase=phase, reveal_all=reveal_all, cashout_multiplier=cashout_multiplier), "mines.png")


def render_mines_transition(state: MinesState, index: int, *, player_name: str | None = None, cashout_multiplier: float | None = None) -> BytesIO:
    # The result is already decided by the backend.  The first frames use a
    # display-only copy with the picked cell still hidden so the reveal reads
    # as an actual transition instead of three identical screenshots.
    hidden = MinesState(
        mine_count=state.mine_count,
        mines=set(state.mines),
        revealed=set(state.revealed) - {int(index)},
        exploded=None,
        finished=False,
    )
    frames = [
        _mines_image(hidden, player_name, phase="MEZŐ KIVÁLASZTVA…", cashout_multiplier=cashout_multiplier),
        _mines_image(hidden, player_name, phase="FELFEDÉS…", flash=index, cashout_multiplier=cashout_multiplier),
        _mines_image(state, player_name, phase="BOMBA!" if state.exploded is not None else "BIZTONSÁGOS", flash=index, cashout_multiplier=cashout_multiplier),
    ]
    return _gif(frames, [180, 300, 850], "mines.gif")


# ---------------------------------------------------------------- Chicken Road


def _chicken_image(state: ChickenRoadState, player_name: str | None, *, phase: str, position: float | None = None, cashout_multiplier: float | None = None) -> Image.Image:
    image, draw = _base("CHICKEN ROAD", player_name, GOLD)
    _center_box(draw, phase, (100, 158, 860, 202), size=22, minimum=14, fill=GREEN if state.alive else RED)
    road=(80, 236, 880, 475)
    draw.rounded_rectangle(road, radius=28, fill=(43,45,55), outline=(78,80,98), width=3)
    lanes=state.max_steps
    lane_w=(road[2]-road[0]-40)/lanes
    for lane in range(lanes+1):
        x=int(road[0]+20+lane*lane_w)
        draw.line((x, road[1]+18, x, road[3]-18), fill=(125,126,136), width=3)
        if lane < lanes:
            mult=chicken_multiplier(lane+1)
            _center_box(draw, f"x{mult:.2f}", (int(x+2), road[3]-53, int(x+lane_w-2), road[3]-18), size=12, minimum=9, fill=GOLD)
    pos = float(state.step if position is None else position)
    chicken_x = road[0]+20 + pos*lane_w
    cy=road[1]+100
    # simple vector chicken
    body=(int(chicken_x-22),cy-18,int(chicken_x+22),cy+20)
    draw.ellipse(body, fill=(247,238,211), outline=(220,174,73), width=3)
    draw.ellipse((int(chicken_x+12),cy-31,int(chicken_x+34),cy-9), fill=(247,238,211), outline=(220,174,73), width=2)
    draw.polygon([(int(chicken_x+33),cy-21),(int(chicken_x+45),cy-16),(int(chicken_x+33),cy-11)], fill=GOLD)
    draw.ellipse((int(chicken_x+26),cy-25,int(chicken_x+30),cy-21), fill=(30,30,35))
    draw.polygon([(int(chicken_x+18),cy-31),(int(chicken_x+23),cy-43),(int(chicken_x+28),cy-31)], fill=RED)
    if not state.alive:
        draw.line((int(chicken_x+23),cy-26,int(chicken_x+31),cy-18), fill=RED, width=3)
        draw.line((int(chicken_x+31),cy-26,int(chicken_x+23),cy-18), fill=RED, width=3)
    hud=(135,526,825,588)
    draw.rounded_rectangle(hud, radius=17, fill=(23,25,37))
    shown_mult = state.multiplier if cashout_multiplier is None else float(cashout_multiplier)
    _center_box(draw, f"LÉPÉS: {state.step}/{state.max_steps}   •   CASHOUT: x{shown_mult:.2f}", (hud[0]+14,hud[1]+7,hud[2]-14,hud[3]-7), size=20, minimum=12, fill=MUTED)
    return image


def render_chicken_road(state: ChickenRoadState, *, player_name: str | None = None, phase: str = "TOVÁBB VAGY CASHOUT?", cashout_multiplier: float | None = None) -> BytesIO:
    return _png(_chicken_image(state, player_name, phase=phase, cashout_multiplier=cashout_multiplier), "chicken_road.png")


def render_chicken_road_transition(before_step: int, state: ChickenRoadState, *, player_name: str | None = None, cashout_multiplier: float | None = None) -> BytesIO:
    """Fast, punchy lane transition.

    Chicken Road is a repeated push-your-luck interaction, so the movement must
    feel responsive instead of forcing the player to watch a ~2 second clip on
    every click.  Ease-out keeps the first half energetic while the final frame
    remains readable long enough to register the result.
    """
    frames=[]
    target = state.step if state.alive else before_step + 0.72
    frame_count = 6
    for i in range(frame_count):
        linear = (i + 1) / frame_count
        t = 1.0 - (1.0 - linear) ** 3
        pos = before_step + (target - before_step) * t
        phase = "ÁTKELÉS…" if i < frame_count - 1 else ("ÁTÉRTÉL" if state.alive else "ELÜTÖTTEK")
        frames.append(_chicken_image(state, player_name, phase=phase, position=pos, cashout_multiplier=cashout_multiplier))
    return _gif(frames, [65, 70, 80, 90, 110, 360], "chicken_road.gif")


# ---------------------------------------------------------------- Plinko

PLINKO_W, PLINKO_H = 1280, 700
PLINKO_TOP_Y = 145
PLINKO_ROW_GAP = 41
PLINKO_PEG_GAP = 86
PLINKO_SLOT_X0 = 150
PLINKO_SLOT_X1 = PLINKO_W - 150
PLINKO_SLOT_Y0 = 540
PLINKO_SLOT_Y1 = 600
PLINKO_LANDING_Y = 532
PLINKO_ANIM_SUBSTEPS = 3
PLINKO_ANIM_STAGGER_FRAMES = 2
PLINKO_ANIM_FRAME_MS = 50
PLINKO_ANIM_FINAL_MS = 300


def plinko_animation_duration_seconds(ball_count: int) -> float:
    count = max(1, min(10, int(ball_count)))
    # +3: one exact idle start frame, the motion timeline, and one exact idle final frame.
    frames = PLINKO_ROWS * PLINKO_ANIM_SUBSTEPS + (count - 1) * PLINKO_ANIM_STAGGER_FRAMES + 3
    return ((frames - 1) * PLINKO_ANIM_FRAME_MS + PLINKO_ANIM_FINAL_MS) / 1000.0


def plinko_static_swap_delay_seconds(ball_count: int) -> float:
    """When to replace GIF with its pixel-identical PNG final frame.

    We start the PNG edit shortly after the GIF has entered its long final idle
    frame instead of waiting until that hold has fully expired. The player is
    already looking at the exact PNG pixels, so network/upload latency is hidden
    inside the final hold and the transition feels much less like a pop.
    """
    total = plinko_animation_duration_seconds(ball_count)
    final_hold = PLINKO_ANIM_FINAL_MS / 1000.0
    return max(0.08, total - final_hold + 0.06)


def _plinko_geometry():
    cx = PLINKO_W / 2
    coords = []
    for row in range(PLINKO_ROWS):
        count = row + 1
        start = cx - (count - 1) * PLINKO_PEG_GAP / 2
        coords.append([(start + i * PLINKO_PEG_GAP, PLINKO_TOP_Y + row * PLINKO_ROW_GAP) for i in range(count)])
    return coords


def _plinko_slot_color(index: int, count: int) -> tuple[int, int, int]:
    # Locked clean-dark Yoru language: purple body with a stronger magenta glow
    # on rare outer slots. The Discord buttons underneath remain native colors.
    distance = abs(index - (count - 1) / 2) / max(1.0, (count - 1) / 2)
    if distance > 0.78:
        return CASINO_MAGENTA
    if distance > 0.38:
        return CASINO_ACCENT
    return (116, 67, 154)


def _plinko_ball_position(result: PlinkoResult, progress: float) -> tuple[float, float]:
    progress = max(0.0, min(float(PLINKO_ROWS), float(progress)))
    step = min(PLINKO_ROWS, int(progress))
    frac = progress - step
    rights = sum(result.path[:step])
    x0 = PLINKO_W / 2 + (rights - step / 2) * PLINKO_PEG_GAP
    y0 = PLINKO_TOP_Y - 24 + step * PLINKO_ROW_GAP
    if step >= PLINKO_ROWS:
        slot_w = (PLINKO_SLOT_X1 - PLINKO_SLOT_X0) / len(PLINKO_MULTIPLIERS)
        return PLINKO_SLOT_X0 + (result.slot + 0.5) * slot_w, PLINKO_LANDING_Y
    next_rights = rights + int(result.path[step])
    x1 = PLINKO_W / 2 + (next_rights - (step + 1) / 2) * PLINKO_PEG_GAP
    y1 = PLINKO_TOP_Y - 24 + (step + 1) * PLINKO_ROW_GAP
    # fractional progress makes the ball visibly travel between pegs instead of teleporting row-by-row
    x = x0 + (x1 - x0) * frac
    y = y0 + (y1 - y0) * frac - math.sin(frac * math.pi) * 10
    return x, y


@lru_cache(maxsize=8)
def _plinko_background(selected_bet: int) -> Image.Image:
    """Static Plinko board cached by selected bet.

    The old renderer redrew every peg, multiplier cell and header text for every
    GIF frame. Caching the immutable board removes most of the CPU wait before
    Discord can upload/play a batch animation.
    """
    image = Image.new("RGB", (PLINKO_W, PLINKO_H), CASINO_BG)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((14, 14, PLINKO_W - 14, PLINKO_H - 14), radius=22, fill=CASINO_PANEL, outline=CASINO_BORDER, width=2)
    draw.rounded_rectangle((14, 14, 21, PLINKO_H - 14), radius=3, fill=CASINO_ACCENT)

    draw.text((42, 24), "PLINKO", font=_font(44, True), fill=CASINO_TEXT)
    draw.text((44, 73), "Yoru Casino", font=_font(17, False), fill=(181, 122, 239))
    bet_text = compact_amount(selected_bet)
    bw = draw.textbbox((0, 0), bet_text, font=_font(29, True))[2]
    draw.text((PLINKO_W - 42 - bw, 28), bet_text, font=_font(29, True), fill=CASINO_TEXT)
    label = "BET AMOUNT"
    lw = draw.textbbox((0, 0), label, font=_font(13, False))[2]
    draw.text((PLINKO_W - 42 - lw, 66), label, font=_font(13, False), fill=(203, 145, 241))

    board = (58, 98, PLINKO_W - 58, 606)
    draw.rounded_rectangle(board, radius=20, fill=(20, 21, 29), outline=(47, 48, 60), width=2)
    coords = _plinko_geometry()
    draw.line((PLINKO_W / 2, 112, 152, 533), fill=(91, 79, 104), width=4)
    draw.line((PLINKO_W / 2, 112, PLINKO_W - 152, 533), fill=(91, 79, 104), width=4)
    for row in coords:
        for x, y in row:
            draw.ellipse((x - 9, y - 9, x + 9, y + 9), fill=(224, 225, 231), outline=(105, 107, 120), width=2)

    table = PLINKO_MULTIPLIERS
    slot_count = len(table)
    sx, ex = PLINKO_SLOT_X0, PLINKO_SLOT_X1
    slot_w = (ex - sx) / slot_count
    for i, mult in enumerate(table):
        x0 = sx + i * slot_w
        x1 = sx + (i + 1) * slot_w - 4
        accent = _plinko_slot_color(i, slot_count)
        draw.rounded_rectangle((x0, PLINKO_SLOT_Y0, x1, PLINKO_SLOT_Y1), radius=6, fill=(32, 24, 41), outline=accent, width=2)
        text = f"{mult:g}x"
        _center_box(draw, text, (int(x0 + 3), PLINKO_SLOT_Y0 + 4, int(x1 - 3), PLINKO_SLOT_Y1 - 4), size=20, minimum=13, fill=accent, bold=True)
    return image


def _plinko_image(
    results: Iterable[PlinkoResult] = (),
    *,
    selected_bet: int,
    stats: CasinoVisualStats | None = None,
    progresses: Iterable[float | None] | None = None,
) -> Image.Image:
    results = tuple(results)
    stats = stats or CasinoVisualStats(bet=selected_bet)
    progress_values = tuple(progresses) if progresses is not None else tuple(None for _ in results)
    if len(progress_values) < len(results):
        progress_values = progress_values + tuple(None for _ in range(len(results) - len(progress_values)))

    image = _plinko_background(int(selected_bet)).copy()
    draw = ImageDraw.Draw(image)
    sx, ex = PLINKO_SLOT_X0, PLINKO_SLOT_X1
    slot_w = (ex - sx) / len(PLINKO_MULTIPLIERS)

    ball_colors = (
        (196, 115, 255), (245, 91, 178), (150, 109, 245), (218, 135, 255), (176, 73, 219),
        (236, 113, 199), (136, 94, 236), (204, 88, 249), (242, 120, 168), (163, 106, 247),
    )
    for idx, (result, prog) in enumerate(zip(results, progress_values)):
        color = ball_colors[idx % len(ball_colors)]
        if prog is not None and prog < 0:
            continue
        if prog is None or prog >= PLINKO_ROWS:
            x = sx + (result.slot + 0.5) * slot_w
            y = PLINKO_LANDING_Y
        else:
            x, y = _plinko_ball_position(result, prog)
        r = 17 if len(results) <= 5 else 14
        draw.ellipse((x - r - 4, y - r - 4, x + r + 4, y + r + 4), fill=(44, 26, 54))
        draw.ellipse((x - r, y - r, x + r, y + r), fill=color, outline=(244, 214, 255), width=2)

    hud = (58, 615, PLINKO_W - 58, 679)
    draw.rounded_rectangle(hud, radius=13, fill=CASINO_PANEL_SOFT, outline=CASINO_BORDER, width=1)
    columns = [
        ("ACTIVE BALLS", f"{max(0, int(stats.active))} / {max(1, int(stats.active_limit))}", CASINO_ACCENT),
        ("TOTAL BET", compact_amount(stats.total_bet), CASINO_ACCENT),
        ("PROFIT / LOSS", compact_amount(stats.profit), CASINO_GREEN if stats.profit >= 0 else CASINO_RED),
    ]
    col_w = (hud[2] - hud[0]) / len(columns)
    for i, (label, value, color) in enumerate(columns):
        x0 = hud[0] + i * col_w
        x1 = hud[0] + (i + 1) * col_w
        if i:
            draw.line((x0, hud[1] + 10, x0, hud[3] - 10), fill=(66, 67, 79), width=1)
        _center_box(draw, label, (int(x0 + 8), hud[1] + 5, int(x1 - 8), hud[1] + 28), size=15, minimum=11, fill=CASINO_MUTED, bold=False)
        _center_box(draw, value, (int(x0 + 8), hud[1] + 27, int(x1 - 8), hud[3] - 5), size=25, minimum=16, fill=color, bold=True)
    return image


def render_plinko_panel(
    *,
    selected_bet: int,
    active_balls: int = 0,
    active_limit: int = 10,
    total_bet: int = 0,
    profit: int = 0,
    results: Iterable[PlinkoResult] = (),
) -> BytesIO:
    stats = CasinoVisualStats(selected_bet, active_balls, max(1, int(active_limit)), total_bet, profit)
    return _png(_plinko_image(tuple(results), selected_bet=selected_bet, stats=stats), "plinko.png")


def render_plinko_animation(
    results: Iterable[PlinkoResult],
    *,
    selected_bet: int,
    active_limit: int = 10,
    total_bet: int,
    profit: int,
    base_total_bet: int | None = None,
    base_profit: int | None = None,
    ball_bets: Iterable[int] | None = None,
    ball_profits: Iterable[int] | None = None,
) -> BytesIO:
    """Render one non-looping Plinko batch with a progressive HUD timeline.

    Backend settlement may already be final before the GIF is created, but the
    visual HUD must not spoil the batch result.  TOTAL BET and PROFIT/LOSS only
    advance when each ball visually reaches its slot.  A landed ball is shown
    for one frame, then disappears; the final frame is a clean empty board.
    """
    results = tuple(results)[:10]
    if not results:
        return render_plinko_panel(
            selected_bet=selected_bet,
            active_limit=active_limit,
            total_bet=total_bet,
            profit=profit,
        )

    count = len(results)
    final_total_bet = int(total_bet)
    final_profit = int(profit)
    if base_total_bet is None:
        base_total_bet = final_total_bet
    if base_profit is None:
        base_profit = final_profit
    base_total_bet = int(base_total_bet)
    base_profit = int(base_profit)

    bets = tuple(int(v) for v in (ball_bets or ()))[:count]
    profits = tuple(int(v) for v in (ball_profits or ()))[:count]
    if len(bets) < count:
        bets = bets + (0,) * (count - len(bets))
    if len(profits) < count:
        profits = profits + (0,) * (count - len(profits))

    # Frame 0 is intentionally the exact previous idle state. This makes
    # PNG -> GIF start from the PNG the player was already looking at.
    motion_frame_count = PLINKO_ROWS * PLINKO_ANIM_SUBSTEPS + (count - 1) * PLINKO_ANIM_STAGGER_FRAMES + 1
    frame_count = motion_frame_count + 2
    frames: list[Image.Image] = []
    durations: list[int] = []
    landing_frame = PLINKO_ROWS * PLINKO_ANIM_SUBSTEPS

    start_stats = CasinoVisualStats(selected_bet, 0, max(1, int(active_limit)), base_total_bet, base_profit)
    frames.append(_plinko_image((), selected_bet=selected_bet, stats=start_stats, progresses=()))
    durations.append(PLINKO_ANIM_FRAME_MS)

    for frame in range(1, frame_count):
        is_final_empty = frame == frame_count - 1
        if is_final_empty:
            stats = CasinoVisualStats(selected_bet, 0, max(1, int(active_limit)), final_total_bet, final_profit)
            frames.append(_plinko_image((), selected_bet=selected_bet, stats=stats, progresses=()))
            durations.append(PLINKO_ANIM_FINAL_MS)
            continue

        motion_frame = frame - 1
        progresses: list[float | None] = []
        active = 0
        landed_indices: list[int] = []
        for index, _result in enumerate(results):
            local_frame = motion_frame - index * PLINKO_ANIM_STAGGER_FRAMES
            if local_frame < 0:
                progresses.append(-1.0)
                continue
            if local_frame < landing_frame:
                progresses.append(float(local_frame) / PLINKO_ANIM_SUBSTEPS)
                active += 1
                continue

            # Financial result becomes visible exactly when this ball lands.
            landed_indices.append(index)
            # Show it in the slot for one frame only; afterwards hide it so
            # landed balls never pile up while later balls are still falling.
            if local_frame == landing_frame:
                progresses.append(None)
            else:
                progresses.append(-2.0)

        shown_total_bet = base_total_bet + sum(bets[i] for i in landed_indices)
        shown_profit = base_profit + sum(profits[i] for i in landed_indices)
        stats = CasinoVisualStats(
            selected_bet,
            active,
            max(1, int(active_limit)),
            shown_total_bet,
            shown_profit,
        )
        frames.append(_plinko_image(results, selected_bet=selected_bet, stats=stats, progresses=progresses))
        durations.append(PLINKO_ANIM_FRAME_MS)

    return _gif(frames, durations, "plinko.gif", loop=None, colors=64, shared_palette=True, disposal=1)


def render_plinko_round_media(
    results: Iterable[PlinkoResult],
    *,
    selected_bet: int,
    active_limit: int = 10,
    total_bet: int,
    profit: int,
    base_total_bet: int | None = None,
    base_profit: int | None = None,
    ball_bets: Iterable[int] | None = None,
    ball_profits: Iterable[int] | None = None,
) -> tuple[bytes, bytes]:
    """Render the GIF and its exact final-frame PNG in one worker call.

    This is used by the Plinko controller while the atomic DB settlement runs
    concurrently. Nothing is uploaded until settlement succeeds.
    """
    gif_fp = render_plinko_animation(
        results,
        selected_bet=selected_bet,
        active_limit=active_limit,
        total_bet=total_bet,
        profit=profit,
        base_total_bet=base_total_bet,
        base_profit=base_profit,
        ball_bets=ball_bets,
        ball_profits=ball_profits,
    )
    gif_payload = gif_fp.getvalue()
    png_payload = render_plinko_final_snapshot(gif_payload).getvalue()
    return gif_payload, png_payload


def render_plinko_final_snapshot(animation: bytes | bytearray | BytesIO) -> BytesIO:
    """Extract the decoded final GIF frame as a PNG idle snapshot.

    Using the GIF's own quantized final frame makes the ANIMATED -> STATIC swap
    visually identical instead of subtly changing palette/colors on cleanup.
    """
    if isinstance(animation, BytesIO):
        raw = animation.getvalue()
    else:
        raw = bytes(animation)
    with Image.open(BytesIO(raw)) as gif:
        gif.seek(max(0, int(getattr(gif, "n_frames", 1)) - 1))
        final = gif.convert("RGB")
    return _png(final, "plinko_idle.png")


def render_plinko(result: PlinkoResult, *, selected_bet: int, total_bet: int, profit: int) -> BytesIO:
    return render_plinko_panel(selected_bet=selected_bet, active_balls=0, active_limit=1, total_bet=total_bet, profit=profit, results=(result,))


# ---------------------------------------------------------------- Candy Rush

# Candy Rush deliberately uses a brighter, game-first presentation than the
# surrounding Casino chrome.  The engine still owns all outcomes; this module
# only animates the already-decided cascade snapshots.
CANDY_ACCENT = (238, 78, 184)
CANDY_BOARD = (86, 42, 139)
CANDY_BOARD_INNER = (116, 57, 166)
CANDY_TILE_A = (151, 82, 188)
CANDY_TILE_B = (135, 70, 177)
CANDY_SKY = (78, 201, 237)


def _ease_out_cubic(value: float) -> float:
    t = max(0.0, min(1.0, float(value)))
    return 1.0 - (1.0 - t) ** 3


def _candy_geometry() -> tuple[int, int, int, int, tuple[int, int, int, int]]:
    cell = 60
    gap = 5
    grid_w = CANDY_COLS * cell + (CANDY_COLS - 1) * gap
    grid_h = CANDY_ROWS * cell + (CANDY_ROWS - 1) * gap
    sx = (W - grid_w) // 2
    sy = 202
    board = (sx - 28, sy - 22, sx + grid_w + 28, sy + grid_h + 18)
    return cell, gap, sx, sy, board


def _draw_candy_icon(draw: ImageDraw.ImageDraw, symbol: str, box: tuple[float, float, float, float], *, glow: bool = False) -> None:
    x0, y0, x1, y1 = [int(round(v)) for v in box]
    w = x1 - x0
    h = y1 - y0
    cx = (x0 + x1) // 2
    cy = (y0 + y1) // 2
    pad = max(4, int(min(w, h) * 0.13))

    if glow:
        draw.ellipse((x0 + 2, y0 + 2, x1 - 2, y1 - 2), fill=(255, 225, 108), outline=(255, 247, 190), width=3)

    if symbol == "CHERRY":
        r = max(7, int(w * 0.19))
        draw.line((cx - 8, cy - 5, cx, y0 + pad + 3), fill=(83, 176, 92), width=4)
        draw.line((cx + 10, cy - 3, cx, y0 + pad + 3), fill=(83, 176, 92), width=4)
        draw.ellipse((cx - r - 8, cy - 2, cx + r - 8, cy + 2 * r - 2), fill=(244, 62, 94), outline=(174, 34, 65), width=2)
        draw.ellipse((cx - r + 13, cy - 1, cx + r + 13, cy + 2 * r - 1), fill=(255, 83, 102), outline=(174, 34, 65), width=2)
        draw.ellipse((cx - 14, y0 + pad + 1, cx + 2, y0 + pad + 10), fill=(94, 202, 96))
    elif symbol == "LEMON":
        draw.ellipse((x0 + pad, y0 + pad + 7, x1 - pad, y1 - pad - 7), fill=(255, 218, 67), outline=(224, 158, 37), width=3)
        draw.arc((x0 + pad + 8, y0 + pad + 13, x1 - pad - 8, y1 - pad - 10), 200, 330, fill=(255, 247, 166), width=3)
        draw.ellipse((x1 - pad - 9, y0 + pad - 1, x1 - pad + 7, y0 + pad + 9), fill=(83, 190, 89))
    elif symbol == "GRAPE":
        grape = (160, 87, 218)
        rr = max(6, int(w * 0.12))
        for ox, oy in ((-11,-10),(8,-10),(-20,5),(0,6),(19,5),(-10,20),(10,20),(0,33)):
            draw.ellipse((cx + ox - rr, cy + oy - rr, cx + ox + rr, cy + oy + rr), fill=grape, outline=(104, 54, 157), width=2)
        draw.polygon([(cx-5,y0+pad+4),(cx+18,y0+pad+1),(cx+7,y0+pad+17)], fill=(86,191,87))
    elif symbol == "BELL":
        # Wrapped orange candy rather than a literal bell: much closer to the
        # candy-game visual language while keeping the backend symbol stable.
        body = (x0 + pad + 8, y0 + pad + 8, x1 - pad - 8, y1 - pad - 8)
        draw.rounded_rectangle(body, radius=12, fill=(255, 159, 55), outline=(215, 92, 35), width=3)
        draw.polygon([(body[0],cy-8),(x0+3,cy-18),(x0+3,cy+18),(body[0],cy+8)], fill=(255,194,76))
        draw.polygon([(body[2],cy-8),(x1-3,cy-18),(x1-3,cy+18),(body[2],cy+8)], fill=(255,194,76))
        draw.line((body[0]+7, body[1]+10, body[2]-7, body[3]-10), fill=(255,220,126), width=4)
    elif symbol == "DIAMOND":
        top = y0 + pad
        bottom = y1 - pad
        left = x0 + pad
        right = x1 - pad
        draw.polygon([(cx,top),(right,cy-3),(cx,bottom),(left,cy-3)], fill=(73, 203, 239), outline=(38, 116, 205))
        draw.polygon([(cx,top+5),(right-7,cy-4),(cx,cy-2)], fill=(139, 235, 255))
        draw.line((left+5,cy-3,right-5,cy-3), fill=(209,249,255), width=2)
    else:  # SEVEN -> glossy pink jelly bean / heart-like candy
        draw.ellipse((x0 + pad + 2, y0 + pad + 8, x1 - pad - 2, y1 - pad - 5), fill=(255, 91, 180), outline=(198, 44, 132), width=3)
        draw.polygon([(cx-20,cy-4),(cx,cy+24),(cx+20,cy-4)], fill=(255, 91, 180))
        draw.arc((x0+pad+8,y0+pad+13,x1-pad-10,y1-pad-13), 205, 300, fill=(255,205,236), width=4)


def _candy_shell(player_name: str | None, *, phase: str, cascade_no: int, multiplier: float) -> tuple[Image.Image, ImageDraw.ImageDraw, int, int, int, int, tuple[int,int,int,int]]:
    image, draw = _base("CANDY RUSH", player_name, CANDY_ACCENT)
    cell, gap, sx, sy, board = _candy_geometry()

    # Bright arcade playfield inside Yoru's outer frame.
    draw.rounded_rectangle(board, radius=28, fill=CANDY_BOARD, outline=(255, 117, 211), width=4)
    inner=(board[0]+10,board[1]+10,board[2]-10,board[3]-10)
    draw.rounded_rectangle(inner, radius=22, fill=CANDY_BOARD_INNER, outline=(197,111,224), width=2)
    # Decorative bubbles make the background read as a candy game rather than
    # a generic dark grid without adding external image assets.
    for bx,by,rr,color in ((board[0]+25,board[1]+34,13,(95,210,238)),(board[2]-34,board[1]+45,17,(255,126,198)),(board[0]+35,board[3]-38,15,(255,193,78)),(board[2]-28,board[3]-52,11,(91,224,154))):
        draw.ellipse((bx-rr,by-rr,bx+rr,by+rr), fill=color)

    # Original-style side information cards; they leave the grid itself large
    # and uncluttered.
    left=(58,248,218,345); right=(742,248,902,345)
    for box, accent in ((left,(111,208,242)),(right,(255,116,205))):
        draw.rounded_rectangle(box,radius=19,fill=(49,35,76),outline=accent,width=3)
    _center_box(draw,"CASCADE",(left[0]+8,left[1]+8,left[2]-8,left[1]+42),size=15,minimum=11,fill=MUTED)
    _center_box(draw,str(cascade_no),(left[0]+8,left[1]+39,left[2]-8,left[3]-8),size=34,minimum=20,fill=TEXT)
    _center_box(draw,"WIN",(right[0]+8,right[1]+8,right[2]-8,right[1]+42),size=15,minimum=11,fill=MUTED)
    _center_box(draw,f"x{multiplier:.2f}",(right[0]+8,right[1]+39,right[2]-8,right[3]-8),size=27,minimum=15,fill=GOLD)
    _center_box(draw,phase,(96,156,864,194),size=21,minimum=13,fill=GOLD)

    # Faint checker cells only; candies themselves remain the focus.
    for r in range(CANDY_ROWS):
        for c in range(CANDY_COLS):
            x=sx+c*(cell+gap); y=sy+r*(cell+gap)
            fill=CANDY_TILE_A if (r+c)%2==0 else CANDY_TILE_B
            draw.rounded_rectangle((x+2,y+2,x+cell-2,y+cell-2),radius=14,fill=fill)
    return image, draw, cell, gap, sx, sy, board


def _draw_candy_at(draw: ImageDraw.ImageDraw, symbol: str, *, col: int, row_position: float, cell: int, gap: int, sx: int, sy: int, glow: bool=False) -> None:
    x=sx+col*(cell+gap)
    y=sy+row_position*(cell+gap)
    if y + cell < sy - 3 or y > sy + CANDY_ROWS*(cell+gap):
        return
    _draw_candy_icon(draw,symbol,(x+4,y+4,x+cell-4,y+cell-4),glow=glow)


def _candy_image(grid: Iterable[Iterable[str]], player_name: str | None, *, phase: str, matched: set[tuple[int,int]] | frozenset[tuple[int,int]] = frozenset(), cascade_no: int=0, multiplier: float=0.0, hidden: set[tuple[int,int]] | frozenset[tuple[int,int]] = frozenset(), burst: float=0.0) -> Image.Image:
    grid=[list(row) for row in grid]
    image,draw,cell,gap,sx,sy,_board=_candy_shell(player_name,phase=phase,cascade_no=cascade_no,multiplier=multiplier)
    for r in range(CANDY_ROWS):
        for c in range(CANDY_COLS):
            if (r,c) in hidden:
                continue
            _draw_candy_at(draw,grid[r][c],col=c,row_position=float(r),cell=cell,gap=gap,sx=sx,sy=sy,glow=(r,c) in matched)
    if burst > 0 and matched:
        spread=8+int(18*min(1.0,burst))
        for r,c in matched:
            cx=sx+c*(cell+gap)+cell//2; cy=sy+r*(cell+gap)+cell//2
            for angle in range(0,360,45):
                rad=math.radians(angle)
                x=cx+math.cos(rad)*spread; y=cy+math.sin(rad)*spread
                rr=4 if burst<0.7 else 3
                draw.ellipse((x-rr,y-rr,x+rr,y+rr),fill=(255,231,111))
    return image


def _candy_drop_in_image(grid: Iterable[Iterable[str]], player_name: str | None, *, progress: float) -> Image.Image:
    grid=[list(row) for row in grid]
    image,draw,cell,gap,sx,sy,_board=_candy_shell(player_name,phase="CANDY-K BEESNEK…",cascade_no=0,multiplier=0.0)
    for r in range(CANDY_ROWS):
        for c in range(CANDY_COLS):
            # Tiny column stagger keeps the fall from looking like one rigid sheet.
            local=max(0.0,min(1.0,(progress-c*0.045)/0.78))
            eased=_ease_out_cubic(local)
            start=-CANDY_ROWS-1-r*0.15
            row_pos=start+(r-start)*eased
            _draw_candy_at(draw,grid[r][c],col=c,row_position=row_pos,cell=cell,gap=gap,sx=sx,sy=sy)
    return image


def _candy_gravity_image(before: tuple[tuple[str,...],...], after: tuple[tuple[str,...],...], matched: frozenset[tuple[int,int]], player_name: str | None, *, cascade_no: int, multiplier: float, progress: float) -> Image.Image:
    image,draw,cell,gap,sx,sy,_board=_candy_shell(player_name,phase=f"CASCADE {cascade_no} • ÚJ CANDY-K",cascade_no=cascade_no,multiplier=multiplier)
    eased=_ease_out_cubic(progress)
    for c in range(CANDY_COLS):
        matched_rows={r for r in range(CANDY_ROWS) if (r,c) in matched}
        incoming_count=len(matched_rows)
        survivors=[(r,before[r][c]) for r in range(CANDY_ROWS) if r not in matched_rows]
        # Existing candies fall into their new lower slots.
        for index,(source_row,symbol) in enumerate(survivors):
            target_row=incoming_count+index
            row_pos=source_row+(target_row-source_row)*eased
            _draw_candy_at(draw,symbol,col=c,row_position=row_pos,cell=cell,gap=gap,sx=sx,sy=sy)
        # Newly generated candies enter from above the board.
        for target_row in range(incoming_count):
            symbol=after[target_row][c]
            start_row=target_row-incoming_count-1.0-c*0.08
            row_pos=start_row+(target_row-start_row)*eased
            _draw_candy_at(draw,symbol,col=c,row_position=row_pos,cell=cell,gap=gap,sx=sx,sy=sy)
    return image


def render_candy_rush_animation(result: CandyRushResult, *, player_name: str | None = None) -> BytesIO:
    frames=[];dur=[];total=0.0

    # Every spin visibly enters the playfield.  This is display-only: the full
    # grid and all cascade results were already decided server-side.
    for progress,duration in ((0.22,80),(0.46,90),(0.72,110),(1.0,190)):
        frames.append(_candy_drop_in_image(result.initial,player_name,progress=progress));dur.append(duration)

    if not result.cascades:
        frames.append(_candy_image(result.initial,player_name,phase="NINCS NYERŐ CLUSTER",cascade_no=0,multiplier=0.0));dur.append(720)
    else:
        for cascade in result.cascades:
            next_total=total+cascade.multiplier_delta
            frames.append(_candy_image(cascade.before,player_name,phase=f"TALÁLAT  +x{cascade.multiplier_delta:.2f}",matched=cascade.matched,cascade_no=cascade.number,multiplier=total));dur.append(180)
            frames.append(_candy_image(cascade.before,player_name,phase="POP!",matched=cascade.matched,hidden=cascade.matched,cascade_no=cascade.number,multiplier=next_total,burst=0.55));dur.append(100)
            frames.append(_candy_gravity_image(cascade.before,cascade.after,cascade.matched,player_name,cascade_no=cascade.number,multiplier=next_total,progress=0.38));dur.append(100)
            frames.append(_candy_gravity_image(cascade.before,cascade.after,cascade.matched,player_name,cascade_no=cascade.number,multiplier=next_total,progress=0.72));dur.append(110)
            frames.append(_candy_gravity_image(cascade.before,cascade.after,cascade.matched,player_name,cascade_no=cascade.number,multiplier=next_total,progress=1.0));dur.append(190)
            total=next_total
        frames.append(_candy_image(result.final,player_name,phase="CASCADE VÉGE",cascade_no=len(result.cascades),multiplier=result.multiplier));dur.append(680)
    return _gif(frames,dur,"candy_rush.gif")


def render_candy_rush(result: CandyRushResult, *, player_name: str | None = None) -> BytesIO:
    return _png(_candy_image(result.final,player_name,phase="EREDMÉNY",cascade_no=len(result.cascades),multiplier=result.multiplier),"candy_rush.png")

