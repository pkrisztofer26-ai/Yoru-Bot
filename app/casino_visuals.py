from __future__ import annotations

from io import BytesIO
import math
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont

from app.casino_games import ROULETTE_RED_NUMBERS


CANVAS_BG = (20, 20, 29)
PANEL = (34, 35, 48)
PANEL_ALT = (44, 45, 62)
TEXT = (244, 244, 248)
MUTED = (168, 170, 187)
GOLD = (244, 191, 72)
GREEN = (43, 176, 113)
RED = (210, 57, 75)
BLACK = (27, 28, 34)
PURPLE = (118, 82, 219)
WHITE = (250, 250, 250)


def _player_game_label(player_name: str | None) -> str:
    raw = " ".join(str(player_name or "PLAYER").split()).strip() or "PLAYER"
    if len(raw) > 22:
        raw = raw[:21].rstrip() + "…"
    return f"{raw.upper()}'S GAME"


def _slow_durations(values: list[int] | tuple[int, ...], factor: float = 1.30) -> list[int]:
    return [max(20, int(round(value * factor))) for value in values]


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
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


def _png_file(image: Image.Image, filename: str) -> BytesIO:
    """Fast PNG encoding: visual renderers run often, so prefer low CPU cost."""
    output = BytesIO()
    image.save(output, format="PNG", optimize=False, compress_level=1)
    output.seek(0)
    output.name = filename
    return output


def _gif_file(frames: list[Image.Image], durations: list[int], filename: str) -> BytesIO:
    """Create a single client-side animation so Discord needs only one upload/edit."""
    if not frames:
        raise ValueError("Legalább egy animációs frame szükséges.")
    output = BytesIO()
    palette_frames = [frame.convert("P", palette=Image.Palette.ADAPTIVE, colors=128) for frame in frames]
    palette_frames[0].save(
        output,
        format="GIF",
        save_all=True,
        append_images=palette_frames[1:],
        duration=durations,
        disposal=2,
        optimize=False,
    )
    output.seek(0)
    output.name = filename
    return output


def _rounded_rect(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], radius: int, fill, outline=None, width: int = 1) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def _draw_slot_symbol(draw: ImageDraw.ImageDraw, symbol: str, box: tuple[int, int, int, int]) -> None:
    x1, y1, x2, y2 = box
    cx = (x1 + x2) // 2
    cy = (y1 + y2) // 2
    w = x2 - x1
    h = y2 - y1
    scale = min(w, h)

    if symbol == "🍒":
        r = int(scale * 0.13)
        draw.ellipse((cx - r * 2, cy, cx, cy + r * 2), fill=(217, 42, 62))
        draw.ellipse((cx + r // 2, cy - r // 4, cx + r * 2 + r // 2, cy + r * 2 - r // 4), fill=(232, 55, 72))
        draw.line((cx - r, cy, cx - r // 2, cy - r * 2), fill=(57, 174, 84), width=max(3, r // 4))
        draw.line((cx + r + r // 2, cy, cx, cy - r * 2), fill=(57, 174, 84), width=max(3, r // 4))
        draw.arc((cx - r, cy - r * 3, cx + r * 2, cy), 200, 330, fill=(57, 174, 84), width=max(3, r // 4))
        return
    if symbol == "🍋":
        r = int(scale * 0.22)
        draw.ellipse((cx - r, cy - int(r * 0.72), cx + r, cy + int(r * 0.72)), fill=(244, 211, 67), outline=(255, 232, 100), width=3)
        draw.polygon([(cx + r - 4, cy - r // 2), (cx + r + r // 3, cy - r), (cx + r // 2, cy - r // 4)], fill=(60, 172, 84))
        return
    if symbol == "🍇":
        r = int(scale * 0.075)
        for ox, oy in [(-1,-1),(0,-1),(1,-1),(-1,0),(0,0),(1,0),(-.5,1),(.5,1),(0,2)]:
            px = int(cx + ox * r * 2.1)
            py = int(cy + oy * r * 1.8)
            draw.ellipse((px-r, py-r, px+r, py+r), fill=(132, 75, 196))
        draw.line((cx, cy - r * 4, cx + r, cy - r * 6), fill=(63, 170, 87), width=4)
        return
    if symbol == "🔔":
        bw = int(scale * 0.34)
        bh = int(scale * 0.32)
        draw.pieslice((cx-bw, cy-bh, cx+bw, cy+bh), 180, 360, fill=(244, 190, 52))
        draw.rectangle((cx-bw, cy, cx+bw, cy+bh//2), fill=(244, 190, 52))
        draw.ellipse((cx-bw//6, cy+bh//3, cx+bw//6, cy+bh//3+bw//3), fill=(179, 119, 25))
        draw.line((cx-bw, cy+bh//2, cx+bw, cy+bh//2), fill=(255, 220, 92), width=4)
        return
    if symbol == "💎":
        r = int(scale * 0.28)
        points = [(cx, cy-r), (cx+r, cy-r//4), (cx+r//2, cy+r), (cx-r//2, cy+r), (cx-r, cy-r//4)]
        draw.polygon(points, fill=(64, 185, 236), outline=(160, 230, 255))
        draw.line((cx-r, cy-r//4, cx+r, cy-r//4), fill=(190, 240, 255), width=3)
        draw.line((cx, cy-r, cx-r//2, cy+r), fill=(190, 240, 255), width=2)
        draw.line((cx, cy-r, cx+r//2, cy+r), fill=(190, 240, 255), width=2)
        return
    if symbol == "7️⃣":
        font = _font(int(scale * 0.55), bold=True)
        text = "7"
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
        draw.text((cx-tw/2, cy-th/2-6), text, font=font, fill=(231, 61, 68), stroke_width=2, stroke_fill=(255, 220, 93))
        return
    if symbol == "⭐":
        r = scale * 0.31
        points = []
        for i in range(10):
            angle = -math.pi/2 + i * math.pi/5
            rr = r if i % 2 == 0 else r * 0.43
            points.append((cx + math.cos(angle)*rr, cy + math.sin(angle)*rr))
        draw.polygon(points, fill=(255, 202, 57), outline=(255, 235, 143))
        font = _font(int(scale * 0.11), bold=True)
        text = "WILD"
        bbox = draw.textbbox((0, 0), text, font=font)
        draw.text((cx-(bbox[2]-bbox[0])/2, cy+scale*0.30), text, font=font, fill=GOLD)
        return
    if symbol == "💰":
        bag_w = int(scale * 0.38)
        bag_h = int(scale * 0.42)
        _rounded_rect(draw, (cx-bag_w//2, cy-bag_h//3, cx+bag_w//2, cy+bag_h//2), max(8, bag_w//5), (218, 170, 57), outline=(255, 222, 119), width=3)
        draw.polygon([(cx-bag_w//4, cy-bag_h//3), (cx+bag_w//4, cy-bag_h//3), (cx+bag_w//6, cy-bag_h//2), (cx-bag_w//6, cy-bag_h//2)], fill=(169, 112, 36))
        font = _font(int(scale*0.22), bold=True)
        text = "$"
        bbox = draw.textbbox((0,0), text, font=font)
        draw.text((cx-(bbox[2]-bbox[0])/2, cy-(bbox[3]-bbox[1])/2), text, font=font, fill=(87, 63, 23))
        return

    font = _font(int(scale * 0.32), bold=True)
    bbox = draw.textbbox((0, 0), symbol, font=font)
    draw.text((cx - (bbox[2]-bbox[0])/2, cy - (bbox[3]-bbox[1])/2), symbol, font=font, fill=TEXT)


def _build_slots_image(
    grid: list[list[str]],
    *,
    stopped_columns: int = 5,
    winning_positions: Iterable[tuple[int, int]] = (),
    spin_label: str = "SPIN",
    motion_phase: int = 0,
    player_name: str | None = None,
) -> Image.Image:
    width, height = 960, 560
    image = Image.new("RGB", (width, height), CANVAS_BG)
    draw = ImageDraw.Draw(image)
    title_font = _font(38, bold=True)
    small_font = _font(20, bold=True)
    draw.text((42, 26), "YORU SLOTS", font=title_font, fill=TEXT)
    draw.text((width-180, 38), spin_label, font=small_font, fill=GOLD)
    owner_label = _player_game_label(player_name)
    owner_box = draw.textbbox((0, 0), owner_label, font=small_font)
    draw.text(((width-(owner_box[2]-owner_box[0]))/2, 42), owner_label, font=small_font, fill=(205, 199, 225))

    frame = (42, 94, width-42, height-42)
    _rounded_rect(draw, frame, 24, PANEL, outline=(84, 79, 116), width=3)
    cols, rows = 5, 3
    gap = 12
    inner_x1, inner_y1 = frame[0]+22, frame[1]+22
    inner_x2, inner_y2 = frame[2]-22, frame[3]-22
    cell_w = (inner_x2-inner_x1-gap*(cols-1)) / cols
    cell_h = (inner_y2-inner_y1-gap*(rows-1)) / rows
    winners = set(winning_positions)

    for r in range(rows):
        for c in range(cols):
            x1 = int(inner_x1 + c*(cell_w+gap)); y1 = int(inner_y1 + r*(cell_h+gap))
            x2 = int(x1+cell_w); y2 = int(y1+cell_h)
            is_winner = (r, c) in winners
            fill = (67, 57, 82) if is_winner else PANEL_ALT
            outline = GOLD if is_winner else (74, 75, 96)
            _rounded_rect(draw, (x1,y1,x2,y2), 18, fill, outline=outline, width=4 if is_winner else 2)
            if c < stopped_columns:
                _draw_slot_symbol(draw, grid[r][c], (x1+8,y1+8,x2-8,y2-8))
            else:
                # Moving bands shift each frame. The GIF animates client-side,
                # so concurrent players do not cause a burst of Discord edits.
                band_gap = max(12, int((y2-y1-30)/5))
                shift = (motion_phase * 9 + c * 5) % band_gap
                for i in range(-1, 6):
                    yy = y1 + 10 + i * band_gap + shift
                    if y1 + 8 <= yy <= y2 - 14:
                        shade = 88 + ((i + motion_phase) % 4) * 10
                        draw.rounded_rectangle((x1+20, yy, x2-20, yy+8), radius=4, fill=(shade, shade-2, min(160, shade+30)))
                draw.text((x1+cell_w/2-12, y1+cell_h/2-18), "↕", font=_font(34, bold=True), fill=MUTED)
    return image


def render_slots(
    grid: list[list[str]],
    *,
    stopped_columns: int = 5,
    winning_positions: Iterable[tuple[int, int]] = (),
    spin_label: str = "SPIN",
    player_name: str | None = None,
) -> BytesIO:
    return _png_file(
        _build_slots_image(
            grid,
            stopped_columns=stopped_columns,
            winning_positions=winning_positions,
            spin_label=spin_label,
            player_name=player_name,
        ),
        "slots.png",
    )


def render_slots_animation(
    grid: list[list[str]],
    *,
    winning_positions: Iterable[tuple[int, int]] = (),
    spin_label: str = "SPIN",
    player_name: str | None = None,
) -> BytesIO:
    """One-upload reel animation. Result is only visible as reels stop."""
    stopped_sequence = (0, 0, 1, 2, 3, 4, 5)
    durations = _slow_durations([110, 120, 140, 160, 190, 230, 600])
    winners = set(winning_positions)
    frames: list[Image.Image] = []
    for index, stopped in enumerate(stopped_sequence):
        frames.append(
            _build_slots_image(
                grid,
                stopped_columns=stopped,
                winning_positions=winners if stopped == 5 else (),
                spin_label=spin_label,
                motion_phase=index,
                player_name=player_name,
            )
        )
    return _gif_file(frames, durations, "slots.gif")


EUROPEAN_WHEEL = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26]


def _wheel_color(number: int) -> tuple[int, int, int]:
    if number == 0:
        return (28, 151, 88)
    return RED if number in ROULETTE_RED_NUMBERS else BLACK


def _build_roulette_image(*, ball_number: int | None = None, result_number: int | None = None, phase: str = "PLACE YOUR BET", player_name: str | None = None) -> Image.Image:
    width, height = 960, 660
    image = Image.new("RGB", (width, height), CANVAS_BG)
    draw = ImageDraw.Draw(image)
    title_font = _font(38, bold=True)
    small_font = _font(20, bold=True)
    number_font = _font(19, bold=True)
    center_font = _font(34, bold=True)
    result_font = _font(66, bold=True)

    draw.text((42, 26), "YORU ROULETTE", font=title_font, fill=TEXT)
    draw.text((width-260, 42), phase, font=small_font, fill=GOLD)
    cx, cy = width//2, 360
    outer = 245
    inner = 118
    step = 360 / len(EUROPEAN_WHEEL)

    draw.ellipse((cx-outer-18, cy-outer-18, cx+outer+18, cy+outer+18), fill=(16,17,23), outline=(99,89,130), width=5)
    for idx, number in enumerate(EUROPEAN_WHEEL):
        start = -90 + idx*step
        end = start + step + 0.35
        draw.pieslice((cx-outer, cy-outer, cx+outer, cy+outer), start=start, end=end, fill=_wheel_color(number), outline=(226, 216, 191), width=1)
        angle = math.radians((start+end)/2)
        rr = outer - 29
        tx = cx + math.cos(angle)*rr
        ty = cy + math.sin(angle)*rr
        text = str(number)
        bbox = draw.textbbox((0,0), text, font=number_font)
        draw.text((tx-(bbox[2]-bbox[0])/2, ty-(bbox[3]-bbox[1])/2), text, font=number_font, fill=WHITE)

    draw.ellipse((cx-inner-26, cy-inner-26, cx+inner+26, cy+inner+26), fill=(58, 39, 79), outline=GOLD, width=5)
    draw.ellipse((cx-inner, cy-inner, cx+inner, cy+inner), fill=(25, 26, 36), outline=(104, 88, 137), width=3)
    center_text = "YORU"
    bbox = draw.textbbox((0,0), center_text, font=center_font)
    draw.text((cx-(bbox[2]-bbox[0])/2, cy-(bbox[3]-bbox[1])/2-12), center_text, font=center_font, fill=TEXT)
    draw.text((cx-46, cy+30), "CASINO", font=small_font, fill=GOLD)
    owner_label = _player_game_label(player_name)
    owner_font = _font(16, bold=True)
    owner_box = draw.textbbox((0, 0), owner_label, font=owner_font)
    draw.text((cx-(owner_box[2]-owner_box[0])/2, cy+68), owner_label, font=owner_font, fill=(205, 199, 225))

    marker = ball_number if ball_number is not None else result_number
    if marker is not None and marker in EUROPEAN_WHEEL:
        idx = EUROPEAN_WHEEL.index(marker)
        angle = math.radians(-90 + (idx+0.5)*step)
        rr = outer + 4
        bx = cx + math.cos(angle)*rr
        by = cy + math.sin(angle)*rr
        br = 12
        draw.ellipse((bx-br-3, by-br-3, bx+br+3, by+br+3), fill=(24,24,30))
        draw.ellipse((bx-br, by-br, bx+br, by+br), fill=WHITE, outline=(208,208,216), width=2)

    if result_number is not None:
        color_name = "ZÖLD" if result_number == 0 else ("PIROS" if result_number in ROULETTE_RED_NUMBERS else "FEKETE")
        result_text = str(result_number)
        bbox = draw.textbbox((0,0), result_text, font=result_font)
        box = (690, 515, 910, 625)
        _rounded_rect(draw, box, 22, _wheel_color(result_number), outline=(230,220,200), width=3)
        draw.text((800-(bbox[2]-bbox[0])/2, 518), result_text, font=result_font, fill=WHITE)
        cb = draw.textbbox((0,0), color_name, font=small_font)
        draw.text((800-(cb[2]-cb[0])/2, 590), color_name, font=small_font, fill=WHITE)

    return image


def render_roulette(*, ball_number: int | None = None, result_number: int | None = None, phase: str = "PLACE YOUR BET", player_name: str | None = None) -> BytesIO:
    return _png_file(
        _build_roulette_image(ball_number=ball_number, result_number=result_number, phase=phase, player_name=player_name),
        "roulette.png",
    )


def render_roulette_animation(result_number: int, *, frame_count: int = 16, player_name: str | None = None) -> BytesIO:
    """Smooth client-side spin: several fast turns, then a gradual deceleration."""
    if result_number not in EUROPEAN_WHEEL:
        raise ValueError("A roulette eredménye 0 és 36 között legyen.")
    frame_count = max(10, min(20, int(frame_count)))
    target_index = EUROPEAN_WHEEL.index(result_number)
    # Four full wheel rotations plus a partial approach make the motion feel
    # like a real spin instead of a few disconnected pocket jumps.
    total_steps = len(EUROPEAN_WHEEL) * 4 + 23
    start_index = (target_index - total_steps) % len(EUROPEAN_WHEEL)
    durations = _slow_durations([
        75 + int((i / max(1, frame_count - 1)) ** 2 * 220)
        for i in range(frame_count)
    ])
    frames: list[Image.Image] = []
    previous_steps = -1
    for index in range(frame_count):
        t = index / max(1, frame_count - 1)
        # Ease-out: large jumps at the start, increasingly tiny jumps near the
        # winning pocket. Clamp monotonic progress so every frame advances.
        progress = 1.0 - (1.0 - t) ** 2.75
        steps = int(round(total_steps * progress))
        if index < frame_count - 1:
            steps = max(previous_steps + 1, min(total_steps - 1, steps))
        else:
            steps = total_steps
        previous_steps = steps
        final = index == frame_count - 1
        ball_number = EUROPEAN_WHEEL[(start_index + steps) % len(EUROPEAN_WHEEL)]
        frames.append(
            _build_roulette_image(
                ball_number=ball_number,
                result_number=result_number if final else None,
                phase="RESULT" if final else "SPINNING",
                player_name=player_name,
            )
        )
    return _gif_file(frames, durations, "roulette.gif")

