from typing import Collection
from redbot.core import commands, Config, checks
from redbot.core.data_manager import cog_data_path
import discord
from discord.ext import tasks
import aiohttp
import asyncio
import json
import pandas as pd
import matplotlib.pyplot as plt
from pandas.plotting import table 
import pathlib
import datetime
import pytz

class Soccer(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=757509)
        self.base_url = "https://football.elenasport.io/v2"
        self.basic_key = "Basic MXA3cW1hZGJqNzZwZmZqc3Q2OGllZDIxN2Q6bWNsZ29pbTJybHZhYXVqMmIybmZwNDVsMnIzNTE2MWFwYmRvNjZqNzAya3ZpczMzbWJv"
        self.temp_key = None

        self.guild = None
        self.plscore = None
        self.commentary = None
        self.message = None

        self.previous_pl_table = None
        self.previous_cl_table = None
        self.previous_fa_table = None
        self.time_for_loop = datetime.time(hour=12)
        self.subscribed_leagues = ["pl", "fa", "cl"]

        self.league_id_pl = 234
        self.country_id_en = 42
        self.team_id_mc = 2892

        default_global = {
            "guild_id": None,
            "channel_id": None,

            "pl": {
                "league_id": 234,
                "stage_id": None,
                "season_id_latest": None,
                "season_ids": {}
            },
            "cl": {
                "league_id": 7,
                "stages": {},
                "season_id_latest": None,
                "season_ids": {}
            },
            "fa": {
                "league_id": 240,
                "stages": {},
                "season_id_latest": None,
                "season_ids": {}
            },
            
            "country_id_en": 27,
            "team_id_mc": None,
            "live_match_id": None,
            "lineup": None,
        }

        self.config.register_global(**default_global)

        self.fetch_guilds.start()
        self.get_api_key.start()
        task_main = asyncio.create_task(self.match_for_today())
        task_main.add_done_callback(self.exception_catching_callback)

    @commands.Cog.listener()
    async def on_ready(self):
        print("Ready")

    async def cog_unload(self):
        self.get_api_key.cancel()
        self.fetch_live_match.cancel()
        self.get_lineups.cancel()
        self.fetch_guilds.cancel()

    @checks.mod()
    @commands.command(name="testsc")
    async def test_soccer(self, ctx):
        dict = await self.config.pl()
        print(dict)

    async def config_set(self, dict, subdict, value):
        try:
            async with getattr(self.config, dict)() as dict:
                dict[subdict] = value
        except AttributeError:
            pass

    async def config_get(self, dict, subdict = None):
        try: 
            async with getattr(self.config, dict)() as dict:
                if subdict == None:
                    return dict
                else:
                    return dict[subdict]
        except AttributeError:
            pass

    async def reset_live(self):
        await self.config.lineup.set(None)
        await self.config.live_match_id.set(None)

    async def fetch_defaults(self):
        """Get league ids"""
        topic = "/leagues?name="
        topic_cl = topic + "Champions"
        resp = await self.api_call(topic_cl)
        for idx, item in enumerate(resp["data"]):
            if item["name"] == "UEFA Champions League":
                await self.config_set("cl", "league_id", (item["id"]))
        await asyncio.sleep(1)
        topic_pl = "/countries/" + str(await self.config.country_id_en()) + "/leagues"
        resp = await self.api_call(topic_pl)
        for idx, item in enumerate(resp["data"]):
            if item["name"] == "FA Cup":
                await self.config_set("fa", "league_id", (item["id"]))
            elif item["name"] == "Premier League":
                await self.config_set("pl", "league_id", (item["id"]))
        await asyncio.sleep(1)

        """Get season ids"""
        for idx, league in enumerate(self.subscribed_leagues):
            topic = "/leagues/" + str(await self.config_get(league, "league_id")) + "/seasons"
            resp = await self.api_call(topic)
            await self.config_set(league, "season_id_latest", resp["data"][0]["id"])
            dict = await self.config_get(league, "season_ids")
            for idx, item in enumerate(resp["data"]):
                dict[item["id"]] = item["leagueName"]
                await self.config_set(league, "season_ids", dict)
            await asyncio.sleep(1)

        """Get stages"""
        topic = "/seasons/" + str(await self.config_get("pl", "season_id_latest")) + "/stages"
        resp = await self.api_call(topic)
        for idx, item in enumerate(resp["data"]):
            if item["name"] == "Regular Season":
                await self.config_set("pl", "stage_id", item["id"])
        await asyncio.sleep(1)
        topic = "/seasons/" + str(await self.config_get("cl", "season_id_latest")) + "/stages"
        resp = await self.api_call(topic)
        stages = {}
        for idx, item in enumerate(resp["data"]):
            if item["hasStanding"] == True:
                group = str(item["name"]).split(" ")
                stages[group[4]] = item["id"]
        await self.config_set("cl", "stages", stages)
        await asyncio.sleep(1)

        """Get MC team id"""
        topic = "/stages/" + str(await self.config_get("pl", "stage_id")) + "/standing"
        resp = await self.api_call(topic=topic)        
        for idx, item in enumerate(resp["data"]):
            if item["teamName"] == "Manchester City":
                await self.config.team_id_mc.set(item["idTeam"])

    def create_png(self, resp, name, figsize: tuple = (5.5, 6.4), fontsize: int = 11, height: int = None):
        try:
            pathlib.Path(str(cog_data_path(self)) + "/" + name).unlink()
        except:
            pass
        cell_text = []
        ranking = []
        rowColor = []

        for idx, item in enumerate(resp["data"]):
            list = []
            list.append(item["teamName"])
            list.append(item["p"])
            list.append(item["pts"])
            list.append(item["w"])
            list.append(item["d"])
            list.append(item["l"])
            ranking.append(item["pos"])
            cell_text.append(list)
            rowColor.append("grey")

            if item["teamName"] == "Manchester City":
                ranking_mc = item["pos"]
            else:
                ranking_mc = None

        columns = ("Team", "MP", "P", "W", "D", "L")
        colColors = []
        for i in range(len(columns)):
            colColors.append("grey")
        rows = ranking
        colWidths = (0.5, 0.1, 0.1, 0.1, 0.1, 0.1)
        fig, ax = plt.subplots(figsize=figsize)
        ax.axis("off")

        table = ax.table(cellText=cell_text, colLabels=columns, colColours=colColors, rowLabels=rows, rowColours=rowColor, cellLoc="center", colWidths=colWidths, loc="center")
        table.auto_set_font_size(False)
        table.set_fontsize(fontsize)

        for cell in table.get_celld():
            if cell[0] == ranking_mc:
                table[cell].set_facecolor("#56b5fd")
        if height == None:
            height = 1 / len(ranking)
        for pos, cell in table.get_celld().items():
            cell.set_height(height)

        plt.savefig(str(cog_data_path(self) / name), transparent=True)

    async def api_call(self, topic: str = "", identifier: str = "", api_url: str = "", return_status: bool = False, headers: dict = {}):
        if api_url == "":
            api_key = await self.config.api_keys()
            api_url = self.base_url + topic
        
        if headers == {}:
            headers = {
                "Authorization": self.temp_key
            }

        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, headers=headers) as resp:
                dict_resp = json.loads(await resp.text())
                if return_status == False:
                    return dict_resp
                else:
                    return dict_resp, resp.status

    @commands.command(name="mcfclineup")
    async def mcfclineup(self, ctx):
        """Delivers the lineup of Manchester City"""
        pass

    @commands.group(name="table")
    async def table(self, ctx):
        """Standings for various leagues"""
        pass

    @table.command(name="pl", aliases=["Premier League"])
    async def table_pl(self, ctx, season: str = "2020/2021"):
        """Delivers the Premier League table"""
        async with ctx.typing():
            topic = "/stages/" + str(await self.config_get("pl", "stage_id")) + "/standing"
            resp = await self.api_call(topic=topic)

            if resp != self.previous_pl_table:
                self.previous_pl_table = resp
                self.create_png(resp, "rankingpl.png")

            await ctx.send(file=discord.File(str(cog_data_path(self) / "rankingpl.png")))

    @table.command(name="cl", aliases=["Champions League"])
    async def table_cl(self, ctx, group: str = "A"):
        """Delivers the Champions League table"""
        async with ctx.typing():
            stages = await self.config_get("cl", "stages")
            topic = "/stages/" + str(stages[group]) + "/standing"
            resp = await self.api_call(topic=topic)

            if resp != self.previous_cl_table:
                self.previous_cl_table = resp
                figsize = (5, 3)
                fontsize = 11
                height = 0.12
                self.create_png(resp, "rankingcl.png", figsize, fontsize, height)
        await ctx.send(file=discord.File(str(cog_data_path(self) / "rankingcl.png")))

    @commands.command(name="timestamp")
    async def timestamp(self, ctx):
        """Current matchtime"""
        pass

    @commands.command(name="score")
    async def score(self, ctx):
        """Score in the current Manchester City match"""
        pass

    @commands.command(name="mcfcfixtures")
    async def mcfcfixtures(self, ctx):
        """Upcoming fixtures of Manchester City"""
        current_time = datetime.datetime.now(pytz.UTC).strftime("%G-%m-%d")
        year, month, day = current_time.split("-")
        month = int(month) + 1
        if month >= 13:
            month = "01"
            year = int(year) + 1
        next_time = str(year) + "-" + str(month) + "-" + str(day)
        
        topic = "/seasons/" + str(await self.config.season_id_latest()) + "/fixtures?idTeam1=" + str(await self.config.team_id_mc()) + "&from=" + current_time
        resp = await self.api_call(topic=topic)

        embed = discord.Embed(color=discord.Color.blue(), description="Upcomming Fixtures")

        name = []
        value = []

        for idx, match in enumerate(resp["data"]):
            if idx >= 5:
                break
            if (match["idHome"] == await self.config.team_id_mc()) or (match["idAway"] == await self.config.team_id_mc()):
                date, time = match["date"].split(" ")
                name.append(match["homeName"] + " vs. " + match["awayName"])
                value.append(date + " at " + time + "\n" + match["venueName"])

        for i in range(0, len(name)):
            embed.add_field(name=name[i], value=value[i], inline=False)

        await ctx.send(embed=embed)

    @checks.mod()
    @commands.command(name="channel")
    async def channel(self, ctx, channel: discord.TextChannel):
        await self.config.channel_id.set(channel.id)
        await ctx.send("Channel set to {}".format(channel.mention))

    @checks.mod()
    @commands.command(name="update")
    async def update_data(self, ctx):
        async with ctx.typing():
            await self.config.guild_id.set(int(ctx.guild.id))
            self.guild = ctx.guild
            await self.fetch_defaults()
        await ctx.send("Done")

    @checks.mod()
    @commands.command(name="startlive")
    async def startlive(self, ctx):
        self.message = None
        self.plscore = None
        await self.config.live_match_id.set(185860)

        self.fetch_live_match.start()
        await ctx.send("Started")

    @checks.mod()
    @commands.command(name="stoplive")
    async def stoplive(self, ctx):
        self.fetch_live_match.cancel()
        await ctx.send("Stopped")
        if self.message != None:
            try:
                await self.message.delete()
            except:
                pass

    @tasks.loop(seconds=5.0)
    async def fetch_live_match(self):
        if (await self.config.live_match_id()) != None:
            headers = {
                "If-Modified-Since": "Wed, 17 Feb 2021 17:44:44 GMT"
            }

            channel = discord.utils.get(self.guild.channels, id=await self.config.channel_id())
            topic = "/fixtures/" + str(await self.config.live_match_id())
            resp_score, status_score = await self.api_call(topic=topic, return_status=True)

            if resp_score["data"][0]["status"] == "finished":
                if self.message != None:
                    try:
                        await self.message.delete()    
                    except:
                        pass            
                self.fetch_live_match.cancel()

            if (resp_score != self.plscore):
                self.plscore = resp_score
                resp_score = resp_score["data"][0]

                embed = discord.Embed(color=discord.Color.blue(), description="Live Standings")
                name = resp_score["homeName"] + "    " + str(resp_score["team_home_90min_goals"] + resp_score["team_home_ET_goals"]) + " - " + str(resp_score["team_away_90min_goals"] + resp_score["team_away_ET_goals"]) + "   " + resp_score["awayName"]
                embed.add_field(name=name, value="Min: " + str(resp_score["elapsed"]))

                if self.message == None:
                    self.message = await channel.send(embed=embed)
                else:
                    await self.message.edit(embed=embed)         

    @tasks.loop(seconds=1.0, count=1)
    async def fetch_guilds(self):
        if (await self.config.guild_id()) != None:
            for guild in self.bot.guilds:
                if guild.id == await self.config.guild_id():
                    self.guild = guild
                    break

    @tasks.loop(seconds=3000.0)
    async def get_api_key(self):
        async with aiohttp.ClientSession() as session:
            headers = {
                "Authorization": self.basic_key,
                "Content-Type": "application/x-www-form-urlencoded"
            }
            payload = {
                "grant_type": "client_credentials"
            }
            async with session.post("https://oauth2.elenasport.io/oauth2/token", headers=headers, data=payload) as resp:
                if resp.status != 200:
                    print("Something went wrong while fetching the new api key")
                else:
                    resp = json.loads(await resp.text())
                    self.temp_key = resp["token_type"] + " " + resp["access_token"]

    @tasks.loop(seconds=60.0)
    async def get_lineups(self):
        if (await self.config.lineup() == None) and (await self.config.live_match_id() != None):
            topic = "/fixtures/" + str(await self.config.live_match_id()) + "/lineups"
            resp = await self.api_call(topic)
            await self.config.lineup.set(resp["data"])
            for idx, item in enumerate(resp["data"]):
                print(item)

    def exception_catching_callback(self, task):
        if task.exception():
            task.print_stack()

    async def match_for_today(self):
        while True:
            now = datetime.datetime.utcnow()
            date = now.date()
            if now.time() > self.time_for_loop:
                date = now.date() + datetime.timedelta(days=1)
            then = datetime.datetime.combine(date, self.time_for_loop)
            await discord.utils.sleep_until(then)

            await self.reset_live()

            current_time = datetime.datetime.now(pytz.UTC).strftime("%G-%m-%d")
            topic = "/seasons/" + str(await self.config.season_id_latest()) + "/fixtures?idTeam1=" + str(await self.config.team_id_mc()) + "&from=" + current_time
            resp, status = await self.api_call(topic, return_status=True)

            if status == 200:
                for idx, item in enumerate(resp["data"]):
                    if (item["idHome"] == await self.config.team_id_mc()) or (item["idAway"] == await self.config.team_id_mc()):
                        match_date, time = item["date"].split(" ")
                        if match_date == str(date):
                            await self.config.live_match_id.set(item["id"])

                            task_live = asyncio.create_task(self.start_live(item))
                            task_live.add_done_callback(self.exception_catching_callback)

    async def start_live(self, match):
        match_date, time = match["date"].split(" ")
        time = datetime.datetime.strptime(time, "%H:%M:%S")
        time_lineup = time - datetime.timedelta(hours=1)
        time_live = time - datetime.timedelta(minutes=5)

        now = datetime.datetime.utcnow()
        date = now.date()
        if (now.time() > time_lineup) and (self.get_lineups.cancelled() == True):
            self.get_lineups.start()
        if (now.time() > time_live) and (self.fetch_live_match.cancelled() == True):
            self.fetch_live_match.start()
        if (self.get_lineups.cancelled() == False) and (self.fetch_live_match.cancelled() == False):
            self.start_live.cancel()
