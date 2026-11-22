"""Integer-cell image rendering. Seams are drawn only on piece boundaries."""
from functools import cache
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .frame import binary_image
from .geometry import NAMES
from .packing import validate

# Order matches geometry.NAMES. Puzzle hues follow Susan's Math Games' naming sheet.
PUZZLE = ("e99a36","b2d568","3a9364","d85350","79c4e0","ad91d0",
          "367bbc","e99abd","d56b32","6ebc45","7855a3","edc946")
DUSK = ("3d5a70","555473","345f60","704f64","435677","596a61",
        "615878","4a696f","786075","486171","625372","486963")
MONO = ("22262b","303439","282b30","33373b","1c2025","3d4044",
        "2b2f34","25282c","383c40","35383d","1f2327","2e3236")
PALETTES = {"puzzle":PUZZLE,"dusk":DUSK,"mono":MONO}
PALETTE_LABELS = {"puzzle":"Puzzle colors","dusk":"Dusk","mono":"Graphite"}
PAPER = "#f4f2eb"
INK = "#1b2829"
MUTED = "#506463"
TEAL = "#176b6d"
LINE = "#d1d7cf"
MISSING = "#c34f33"
EXTRA = "#087e8b"


def enlarged(image, factor):
    return image.resize((image.width*factor,image.height*factor),Image.Resampling.NEAREST)


def swatches(name, mode):
    base = [tuple(bytes.fromhex(v)) for v in PALETTES[name]]
    if mode == "white" and name != "puzzle":
        # Preserve the positive light field in white-tile mode.
        return [tuple(255-round(v*.69) for v in rgb) for rgb in base]
    return base


def piece_image(owner, kinds, mode, palette, scale):
    fills = swatches(palette, mode)
    background = (255,255,255) if mode == "black" else (11,16,20)
    rgb = np.full(owner.shape+(3,), background, dtype=np.uint8)
    valid = owner >= 0
    if len(kinds):
        rgb[valid] = np.asarray(fills,dtype=np.uint8)[kinds[owner[valid]]]
    image = enlarged(Image.fromarray(rgb),scale)
    if scale < 2:
        return image
    # Draw each inter-piece seam exactly once, on the first pixel of the right/lower cell.
    draw = ImageDraw.Draw(image)
    seam = (61,65,65) if palette == "puzzle" else ((128,143,143) if mode=="white" else
                                                   ((89,95,100) if palette=="mono" else (145,158,163)))
    for y,x in np.argwhere(valid[:,1:] & valid[:,:-1] & (owner[:,1:] != owner[:,:-1])):
        x, y = (int(x)+1)*scale, int(y)*scale
        draw.line((x,y,x,y+scale-1),fill=seam)
    for y,x in np.argwhere(valid[1:] & valid[:-1] & (owner[1:] != owner[:-1])):
        x, y = int(x)*scale, (int(y)+1)*scale
        draw.line((x,y,x+scale-1,y),fill=seam)
    return image


def errors_image(black, recon):
    rgb = np.full(black.shape+(3,), (255,255,255), dtype=np.uint8)
    rgb[black] = (192,199,196)
    rgb[black & ~recon] = (195,79,51)
    rgb[~black & recon] = (8,126,139)
    return Image.fromarray(rgb)


def render_run(record, black, out, palettes=("dusk",)):
    owner,kinds = validate(record,black)
    mode = record["mode"]
    recon = (owner>=0) if mode=="black" else (owner<0)
    scale = max(4,math.ceil(960/record["width"]))
    out = Path(out)
    out.mkdir(parents=True,exist_ok=True)
    mask = binary_image(recon)
    mask.save(out/"mask.png")
    enlarged(mask,scale).save(out/"binary.png")
    for palette in palettes:
        piece_image(owner,kinds,mode,palette,scale).save(out/f"{palette}.png")
    return owner,kinds,recon


@cache
def font(size, bold=False):
    for face in (("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"),
                 ("Arial Bold.ttf" if bold else "Arial.ttf")):
        try:
            return ImageFont.truetype(face,size)
        except OSError:
            pass
    return ImageFont.load_default(size)


def title(draw, x, title_text, subtitle, zoom=1):
    draw.text((x,24*zoom),"BAD APPLE!!   /   00:07.500",font=font(17*zoom,True),fill=TEAL)
    draw.text((x,52*zoom),title_text,font=font(42*zoom,True),fill=INK)
    draw.text((x,111*zoom),subtitle,font=font(22*zoom),fill=MUTED)


def image_panel(canvas, image, x, y, width, height):
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((x-1,y-1,x+width,y+height),fill=LINE)
    draw.rectangle((x,y,x+width-1,y+height-1),fill="#e8ebe6")
    canvas.paste(image,(x+(width-image.width)//2,y+(height-image.height)//2))


def make_sheet(path, heading, subtitle, entries, kind="comparison", palette="dusk"):
    # 1200 is the least common multiple of the five widths. Each resolution thus
    # gets the same footprint, with an integer number of display pixels per cell.
    zoom = 3 if kind == "resolution" else 1
    margin, label, gap, panel = (v*zoom for v in (38,304,18,400))
    panel_h = panel*3//4
    tops = [margin+label+i*(panel+gap) for i in range(3)]
    width = tops[-1]+panel+margin
    head, row_h = 183*zoom, panel_h+36*zoom
    canvas = Image.new("RGB",(width,head+len(entries)*row_h+25*zoom),PAPER)
    d = ImageDraw.Draw(canvas)
    title(d,margin,heading,subtitle,zoom)
    cols = ("Target grid","Reconstruction","Piece boundaries") if kind=="resolution" else (
            "Reconstruction","Piece boundaries","Pixel errors")
    for x,name in zip(tops,cols):
        d.text((x,151*zoom),name,font=font(19*zoom,True),fill=INK)
    for index,(label_text,row,owner,kinds,black,recon) in enumerate(entries):
        y = head+index*row_h
        d.line((margin,y-11*zoom,width-margin,y-11*zoom),fill=LINE,width=zoom)
        d.text((margin,y+18*zoom),label_text,font=font(25*zoom,True),fill=INK)
        details = (f'{row["pieces"]} pieces', f'{row["error_pixels"]} pixel errors',
                   f'{float(row["correct_pct"]):.3f}% correct',
                   f'{float(row["entropy_norm"]):.5f} entropy¹',
                   f'{float(row["solve_s"]):.2f} s total')
        for line,text in enumerate(details):
            d.text((margin,y+(68+31*line)*zoom),text,font=font(20*zoom),fill=MUTED)
        scale = panel//black.shape[1]
        binary = enlarged(binary_image(recon),scale)
        pieces = piece_image(owner,kinds,row["mode"],palette,scale)
        images = (enlarged(binary_image(black),scale), binary,pieces) if kind=="resolution" else (
                  binary,pieces,enlarged(errors_image(black,recon),scale))
        for x,img in zip(tops,images):
            image_panel(canvas,img,x,y,panel,panel_h)
    d.text((margin,canvas.height-34*zoom),"¹ Shannon entropy divided by ln(12).",font=font(16*zoom),fill=MUTED)
    if kind != "resolution":
        x = tops[1]
        for color,caption in ((MISSING,"Missing black pixel"),(EXTRA,"Extra black pixel")):
            d.rectangle((x,canvas.height-31,x+13,canvas.height-18),fill=color)
            d.text((x+23,canvas.height-36),caption,font=font(17),fill=INK)
            x += 236
    canvas.save(path)


def palette_sheet(path, entry):
    _,row,owner,kinds,black,_ = entry
    panel,margin,gap = 480,40,22
    canvas = Image.new("RGB",(2*margin+3*panel+2*gap,682),PAPER)
    d = ImageDraw.Draw(canvas)
    title(d,margin,"Three palettes, one packing",
          f'{row["pieces"]} pieces on the 80 × 60 grid. Each letter below identifies a shape.')
    for index,(key,label) in enumerate(PALETTE_LABELS.items()):
        x = margin+index*(panel+gap)
        d.text((x,159),label,font=font(26,True),fill=INK)
        image_panel(canvas,piece_image(owner,kinds,"black",key,6),x,213,panel,360)
        for j,(letter,color) in enumerate(zip(NAMES,swatches(key,"black"))):
            col, line = j%6, j//6
            sx, sy = x+col*78, 597+line*32
            d.rectangle((sx,sy,sx+19,sy+19),fill=color)
            d.text((sx+28,sy-3),letter,font=font(18,True),fill=INK)
    canvas.save(path)


def overview(path, entry, gray):
    _,row,owner,kinds,black,recon = entry
    margin,panel,gap = 36,480,20
    canvas = Image.new("RGB",(2*margin+3*panel+2*gap,677),PAPER)
    d = ImageDraw.Draw(canvas)
    title(d,margin,"Bad Apple!! in pentominoes",
          "One shadow-animation frame, reconstructed on an 80 × 60 grid.")
    views = (("Original frame",gray.resize((480,360),Image.Resampling.NEAREST)),
             ("Binary reconstruction",enlarged(binary_image(recon),6)),
             ("Individual pentominoes",piece_image(owner,kinds,"black","dusk",6)))
    for i,(caption,im) in enumerate(views):
        x = margin+i*(panel+gap)
        d.text((x,166),caption,font=font(24,True),fill=INK)
        image_panel(canvas,im,x,211,480,360)
    values = (f'{row["pieces"]} pieces  /  {row["types_used"]} shapes',
              f'{row["error_pixels"]} mismatches  /  4,800 pixels',
              f'{float(row["correct_pct"]):.3f}% correct')
    for i,value in enumerate(values):
        d.text((margin+i*(panel+gap),604),value,font=font(24,True),fill=TEAL)
    canvas.save(path)
