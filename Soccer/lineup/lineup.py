import json
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter, ImageOps
from pathlib import Path
import asyncio
import aiohttp
import numpy

async def create_lineup(dict, path, filepath, filename):
    font_size_main = 30
    font_main = ImageFont.truetype("arial.ttf", font_size_main)

    im = Image.open(path + "Background.png")
    im = im.convert("RGBA")
    main_x, main_y = im.size

    im_shirt_home = Image.open(path + "ShirtHome.png")
    im_shirt_home = im_shirt_home.convert("RGBA")
    im_shirt_away = Image.open(path + "ShirtAway.png")
    im_shirt_away = im_shirt_away.convert("RGBA")

    x, y = im_shirt_home.size
    h = font_size_main * 3
    temp_relation = x/y
    w = h * temp_relation
    im_shirt_home = im_shirt_home.resize((int(w), int(h)), resample=Image.BOX)
    im_shirt_away = im_shirt_away.resize((int(w), int(h)), resample=Image.BOX)

    rows = ["1", "3", "5", "7", "9"]
    cols = ["A", "B", "C", "D", "E", "F", "G", "H", "I"]

    col_width = (main_x - 100)  / 5
    col_height = (main_y / 2 - 200) / 9

    dif_width = (main_x - (col_width* 4)) / 2
    pos_x = {}
    for idx, row in enumerate(rows):
        pos_x[row] = (col_width * (idx)) + dif_width

    dif_height = ((main_y / 2) - (col_height * 8)) / 2
    pos_y = {}
    for idx, col in enumerate(cols):    
        pos_y[col] = (col_height * idx) + dif_height

    draw_main = ImageDraw.Draw(im)
    for idx, item in enumerate(dict):
        if item["isStartingXI"] == True:
            im_temp_home = im_shirt_home.copy()
            im_temp_away = im_shirt_away.copy()

            text = item["playerName"]
            number = item["shirtNumber"]

            pos_number = im_shirt_home.size
            x_shirt = int(pos_number[0] / 2)
            y_shirt = int(pos_number[1] / 2)
            font_shirt = ImageFont.truetype("arial.ttf", int(pos_number[1] / 2.2))

            x_player = int(pos_x[str(item["row"])])
            y_player = int(pos_y[item["col"]])

            if item["idTeam"] == 99:
                shirt_home_draw = ImageDraw.Draw(im_temp_home)
                shirt_home_draw.text((x_shirt, y_shirt), number, font=font_shirt, fill="#000000", anchor="mm")

                draw_main.text((x_player, y_player), text, font=font_main, fill="#000000", anchor="mm")
                im.paste(im_temp_home, (x_player - int(pos_number[0] / 2), y_player + font_size_main), im_temp_home)

            else:
                shirt_away_draw = ImageDraw.Draw(im_temp_away)
                shirt_away_draw.text((x_shirt, y_shirt), number, font=font_shirt, fill="#000000", anchor="mm")

                draw_main.text((x_player, main_y - y_player), text, font=font_main, fill="#000000", anchor="mm")
                im.paste(im_temp_away, (x_player - int(pos_number[0] / 2), main_y - y_player - h - font_size_main), im_temp_away)

    im.save(filepath + filename)
