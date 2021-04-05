from typing import Collection
from redbot.core import commands, Config, checks
from redbot.core.data_manager import cog_data_path, bundled_data_path
import discord
from discord.ext import tasks
from .lineup import lineup
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
        self.basic_key = "Basic NGs4a2lzNWlvajI3Z210ZzdxaGgydWJlOXI6MWI5YjY3OG1xOTg2dTB2cHN2ZWhnMnRjZmxrNHR0aWdzMWhyZ3JwZXEzNWJhbDEwNTVvcg=="
        self.temp_key = None

        self.api_key_paid = "d8663eeacb47449aae670796bf27149b"

        self.guild = None
        self.plscore = None
        self.message = None
        self.score = {"homeTeam": 0, "awayTeam": 0}
        self.goals = {}
        self.bookings = {}
        self.substitutions = {}
        self.c_messages = {}
        self.kickoff = False
        self.halftime = False
        self.shalf = False

        self.previous_pl_table = None
        self.previous_cl_table = None
        self.previous_fa_table = None
        self.time_for_loop = datetime.time(hour=0, minute=1)
        self.subscribed_leagues = ["pl", "fa", "cl", "lc"]

        self.league_id_pl = 234
        self.country_id_en = 42
        self.team_id_mc = 2892

        default_global = {
            "guild_id": None,
            "channel_live_id": None,
            "channel_commentary_id": [],

            "pl": {
                "league_id": 0,
                "league_id_elena": 234,
                "stage_id": None,
                "season_id_latest": None,
                "season_ids": {}
            },
            "cl": {
                "league_id": 0,
                "league_id_elena": 7,
                "stages": {},
                "season_id_latest": None,
                "season_ids": {}
            },
            "fa": {
                "league_id": 0,
                "league_id_elena": 240,
                "stages": {},
                "season_id_latest": None,
                "season_ids": {}
            },
            "lc": {
                "league_id": 0,
                "league_id_elena": 241,
                "stages": {},
                "season_id_latest": None,
                "season_ids": {}
            },
            
            "country_id_en": 2072,
            "team_id_mc": None,
            "team_id_mc_elena": 99,
            "live_match_id": None,
            "live_match_id_elena": None,
            "lineup": None,
            "lineup_elena": None,
            "last_match": None,
            "last_matches": [],
            "time": None
        }

        self.config.register_global(**default_global)

        self.fetch_guilds.start()
        self.get_api_key.start()
        task_main = asyncio.create_task(self.match_for_today())
        task_main.add_done_callback(self.exception_catching_callback)

    def cog_unload(self):
        self.get_api_key.cancel()
        self.fetch_live_match.cancel()
        self.get_lineups.cancel()
        self.fetch_guilds.cancel()
        self.start_live.cancel()

    def convert_time(self, time, return_datetime=False):
        time = datetime.datetime.strptime(time, "%Y-%m-%dT%H:%M:%SZ")
        tz_time = pytz.timezone("UTC").localize(time)
        if return_datetime == False:
            london_date = tz_time.astimezone(pytz.timezone("Europe/London")).strftime("%Y-%m-%d")
            london_time = tz_time.astimezone(pytz.timezone("Europe/London")).strftime("%H:%M")
            return london_date, london_time
        else:
            return tz_time.astimezone(pytz.timezone("Europe/London"))

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
        await self.config.lineup_elena.set(None)
        await self.config.live_match_id.set(None)
        await self.config.live_match_id_elena.set(None)
        await self.config.time.set(None)
        self.message = None
        self.plscore = None
        self.goals = []
        self.bookings = []
        self.substitutions = []
        self.score = {"homeTeam": 0, "awayTeam": 0}
        self.kickoff = False
        self.halftime = False
        self.shalf = False

        self.start_live.cancel()
        self.fetch_live_match.cancel()
        self.get_lineups.cancel()

    async def fetch_defaults(self):
        """Get league ids"""
        url = "https://api.football-data.org/v2/competitions"
        resp, status = await self.api_call_paid(url, return_status=True)
        if status == 200:
            for comp in resp["competitions"]:
                if (comp["area"]["name"] == "England") and (comp["name"] == "Premier League"):
                    await self.config_set("pl", "league_id", comp["id"])
                elif comp["name"] == "UEFA Champions League":
                    await self.config_set("cl", "league_id", comp["id"])
                elif (comp["area"]["name"] == "England") and (comp["name"] == "Football League Cup"):
                    await self.config_set("lc", "league_id", comp["id"])
                elif (comp["area"]["name"] == "England") and (comp["name"] == "FA Cup"):
                    await self.config_set("fa", "league_id", comp["id"])                

        for idx, league in enumerate(self.subscribed_leagues):
            topic = "/leagues/" + str(await self.config_get(league, "league_id_elena")) + "/seasons"
            resp, status = await self.api_call(topic, return_status=True)
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

    def create_png(self, resp, name, figsize: tuple = (5.5, 6.4), fontsize: int = 11, height: int = None):
        try:
            pathlib.Path(str(cog_data_path(self)) + "/" + name).unlink()
        except:
            pass
        cell_text = []
        ranking = []
        rowColor = []
        ranking_mc = None

        for idx, item in enumerate(resp["standings"][0]["table"]):
            list = []
            list.append(item["team"]["name"])
            list.append(item["playedGames"])
            list.append(item["points"])
            list.append(item["won"])
            list.append(item["draw"])
            list.append(item["lost"])
            ranking.append(item["position"])
            cell_text.append(list)
            rowColor.append("grey")

            if item["team"]["id"] == 65:
                ranking_mc = item["position"]

        columns = ("Team", "MP", "P", "W", "D", "L")
        colColors = []
        for i in range(len(columns)):
            colColors.append("grey")
        rows = ranking
        colWidths = (0.6, 0.1, 0.1, 0.1, 0.1, 0.1)
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

    async def api_call_paid(self, url: str, return_status: bool = False):
        headers = {
            "X-Auth-Token": self.api_key_paid
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                dict_resp = json.loads(await resp.text())
                if return_status == False:
                    return dict_resp
                else:
                    return dict_resp, resp.status

    async def standings_final(self, ctx):
        async with ctx.typing():
            resp = await self.standings()
            embed = discord.Embed(color=discord.Color.blue(), description="Upcoming Fixtures")

            name = []
            value = []

            for idx, match in enumerate(resp["matches"]):
                if idx > 5:
                    break
                date, time = self.convert_time(match["utcDate"])
                name.append(match["homeTeam"]["name"] + " vs. " + match["awayTeam"]["name"])
                if match["venue"] != None:
                    value.append(date + " at " + time + "\n" + match["venue"] + "\n" + match["competition"]["name"])
                else:
                    value.append(date + " at " + time + "\n" + match["competition"]["name"])

            for i in range(0, len(name)):
                embed.add_field(name=name[i], value=value[i], inline=False)

            await ctx.send(embed=embed)

    async def standings(self):
        time = datetime.datetime.now(pytz.UTC)
        current_time = time.strftime("%G-%m-%d")
        next_time = (time + datetime.timedelta(days=30)).strftime("%G-%m-%d")
        
        url = "http://api.football-data.org/v2/teams/{}/matches?dateFrom={}&dateTo={}".format(65, current_time, next_time)
        resp = await self.api_call_paid(url)

        return resp

    async def clear_live_channel(self, channel):
        async for msg in channel.history(limit=None):
            try:
                await msg.delete()
            except:
                pass

    async def commentary(self, resp):
        resp = resp["match"]
        updated = False
        # if resp["score"]["fullTime"] != self.score:
        #     if resp["score"]["fullTime"]["homeTeam"] != self.score["homeTeam"]:
        #         embed = discord.Embed(color=discord.Color.blue(), description=("Goal for {}!".format(resp["homeTeam"]["name"])))
        #     else:
        #         embed = discord.Embed(color=discord.Color.blue(), description="Goal for {}!".format(resp["awayTeam"]["name"]))
        #     await self.send_commentary(embed, "goal")
        #     updated = True
        #     self.score = resp["score"]["fullTime"]
        if resp["goals"] != self.goals:
            for goal in resp["goals"]:
                if goal not in self.goals:
                    embed = discord.Embed(color=discord.Color.blue(), description="Goal :goal: for {}!".format(goal["team"]["name"]))
                    embed.add_field(name="Scorer", value=goal["scorer"]["name"], inline=True)
                    if goal["assist"] != None:
                        embed.add_field(name="Assist :handshake:", value=goal["assist"]["name"], inline=True)
                    embed.set_footer(text="Min: {}".format(goal["minute"]))
                    await self.send_commentary(embed)
            updated = True
            self.goals = resp["goals"]
        if resp["bookings"] != self.bookings:
            for booking in resp["bookings"]:
                if booking not in self.bookings:
                    if booking["card"] == "YELLOW_CARD":
                        text = "Yellow card :yellow_square: for {} from {}!".format(booking["player"]["name"], booking["team"]["name"])
                    elif booking["card"] == "RED_CARD":
                        text = "Red card :red_square: for {} from {}!".format(booking["player"]["name"], booking["team"]["name"])
                    else:
                        text = "Event not found: {}".format(booking["card"])
                    embed = discord.Embed(color=discord.Color.blue(), description=text)
                    embed.set_footer(text="Min: {}".format(booking["minute"]))
                    await self.send_commentary(embed)
            updated = True
            self.bookings = resp["bookings"]
        if resp["substitutions"] != self.substitutions:
            for substitution in resp["substitutions"]:
                if substitution not in self.substitutions:
                    embed = discord.Embed(color=discord.Color.blue(), description="Substitution :arrows_counterclockwise: for {}!".format(substitution["team"]["name"]))
                    embed.add_field(name="Player in", value=substitution["playerIn"]["name"], inline=True)
                    embed.add_field(name="Player out", value=substitution["playerOut"]["name"], inline=True)
                    embed.set_footer(text="Min: {}".format(substitution["minute"]))
                    await self.send_commentary(embed)
            updated = True
            self.substitutions = resp["substitutions"]

        return updated

    async def send_commentary(self, embed, c_type: str = None):
        channels = await self.config.channel_commentary_id()
        for channel_id in channels:
            if c_type == None:
                channel = discord.utils.get(self.guild.channels, id=channel_id)
                message = await channel.send(embed=embed)
            else:
                for channel_id in channels:
                    if self.c_messages[channel_id] == None:
                        channel = discord.utils.get(self.guild.channels, id=channel_id)
                        message = await channel.send(embed=embed)
                        self.c_messages[channel_id] = message
                    else:
                        await self.c_messages[channel_id].edit(embed=embed)
                        self.c_messages[channel_id] = None

    async def append_previous(self, resp):
        async with self.config.last_matches() as previous:
            if len(previous) <= 5:
                date, time = self.convert_time(resp["match"]["utcDate"])
                previous.append({"name": "{}   {} - {}   {}".format(resp["match"]["homeTeam"]["name"], resp["match"]["score"]["fullTime"]["homeTeam"], resp["match"]["score"]["fullTime"]["awayTeam"], resp["match"]["awayTeam"]["name"]), "value": date + " at " + time + "\n" + resp["match"]["venue"] + "\n" + resp["match"]["competition"]["name"]})
            else:
                previous.pop(0)
                previous.append({"name": "{}   {} - {}   {}".format(resp["match"]["homeTeam"]["name"], resp["match"]["score"]["fullTime"]["homeTeam"], resp["match"]["score"]["fullTime"]["awayTeam"], resp["match"]["awayTeam"]["name"]), "value": date + " at " + time + "\n" + resp["match"]["venue"] + "\n" + resp["match"]["competition"]["name"]})

    # @commands.command(name="mcfclineup")
    # async def lineup(self, ctx):
    #     """Delivers the lineup of Manchester City"""
    #     filename = "lineup.png"
    #     try:
    #         await ctx.send(file=discord.File(str(cog_data_path(self) / filename)))
    #     except:
    #         await ctx.send("No match found.")

    @commands.group(name="table")
    async def table(self, ctx):
        """Standings for various leagues"""
        pass

    @table.command(name="pl", aliases=["PremierLeague"])
    async def table_pl(self, ctx, season: str = "2020/2021"):
        """Delivers the Premier League table"""
        async with ctx.typing():
            url = "https://api.football-data.org/v2/competitions/{}/standings?standingType=TOTAL".format(await self.config_get("pl", "league_id"))
            resp, status = await self.api_call_paid(url, return_status=True)

            if status == 200:
                if resp != self.previous_pl_table:
                    self.previous_pl_table = resp
                    self.create_png(resp, "rankingpl.png")

                await ctx.send(file=discord.File(str(cog_data_path(self) / "rankingpl.png")))

    @table.command(name="cl", aliases=["ChampionsLeague"])
    async def table_cl(self, ctx, group: str = "A"):
        """Delivers the Champions League table"""
        group = group.upper()
        valid_groups = ["A", "B", "C", "D", "E", "F", "G", "H"]
        if not group in valid_groups:
            await ctx.send("Group is not valid. Valid Groups are `A, B, C, D, E, F, G, H`")
        else:
            async with ctx.typing():
                url = "https://api.football-data.org/v2/competitions/{}/standings?standingType=TOTAL".format(await self.config_get("cl", "league_id"))
                resp, status = await self.api_call_paid(url, return_status=True)

            if status == 200:
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
        if self.plscore != None:
            resp_score = self.plscore["match"]
            embed = discord.Embed(color=discord.Color.blue(), description="**Min: **" + str(resp_score["minute"]))
            await ctx.send(embed=embed)           
        else:
            await ctx.send("No live match found")

    @commands.command(name="score")
    async def score(self, ctx):
        """Score in the current Manchester City match"""
        if self.plscore != None:
            resp_score = self.plscore
            if resp_score["match"]["minute"] == "BREAK":
                resp_score["match"]["minute"] = "Half Time"

            embed = discord.Embed(color=discord.Color.blue(), description="Live Standings")
            name = "{}   {} - {}   {}".format(resp_score["match"]["homeTeam"]["name"], resp_score["match"]["score"]["fullTime"]["homeTeam"], resp_score["match"]["score"]["fullTime"]["awayTeam"], resp_score["match"]["awayTeam"]["name"])
            embed.add_field(name=name, value="Min: " + str(resp_score["match"]["minute"]))
            await ctx.send(embed=embed)
        elif await self.config.last_match() != None:
            resp_score = await self.config.last_match()
            resp_score = resp_score["match"]

            embed = discord.Embed(color=discord.Color.blue(), description="Standings of last match")
            date, time = resp_score["utcDate"].split("T")
            hour, min, sec = time.split(":")
            time = "{}:{}".format(hour, min)
            value = "Match from {} at {}".format(date, time)

            name = "{}   {} - {}   {}".format(resp_score["homeTeam"]["name"], resp_score["score"]["fullTime"]["homeTeam"], resp_score["score"]["fullTime"]["awayTeam"], resp_score["awayTeam"]["name"])
            embed.add_field(name=name, value=value)
            await ctx.send(embed=embed)           
        else:
            await ctx.send("No live match found")

    @commands.command(name="previous")
    async def previous(self, ctx):
        """Previous match results
        Shows up to 5 previous match results"""
        previous = await self.config.last_matches()
        if previous == []:
            await ctx.send("No previous matches found.")
        else:
            embed = discord.Embed(color=discord.Color.blue(), description="Previous match results")
            for item in previous:
                embed.add_field(name=item["name"], value=item["value"])
            await ctx.send(embed=embed)

    @commands.command(name="mcfcfixtures")
    async def mcfcfixtures(self, ctx):
        """Upcoming fixtures of Manchester City"""
        await self.standings_final(ctx)

    @checks.mod()
    @commands.group(name="channel")
    async def channel(self, ctx):
        """Channel settings for live posts"""
        pass

    @channel.command(name="live")
    async def channel_live(self, ctx, channel: discord.TextChannel):
        """Channel for standings/match updates"""
        await self.config.channel_live_id.set(channel.id)
        await self.config.guild_id.set(ctx.guild.id)
        await ctx.send("Channel set to {}".format(channel.mention))

    @channel.group(name="commentary")
    async def channel_commentary(self, ctx):
        """Add/remove commentary channel"""
        pass

    @channel_commentary.command(name="add")
    async def channel_commentary_add(self, ctx, channel: discord.TextChannel):
        async with self.config.channel_commentary_id() as current_channels:
            current_channels.append(channel.id)
        self.c_messages[channel.id] = None
        await ctx.send("Channel {} will now receive commentary!".format(channel.mention))

    @channel_commentary.command(name="remove")
    async def channel_commentary_remove(self, ctx, channel: discord.TextChannel):
        async with self.config.channel_commentary_id() as current_channels:
            if channel.id in current_channels:
                current_channels.remove(channel.id)
                await ctx.send("Channel {} removed".format(channel.mention))
            else:
                await ctx.send("Channel {} is not added yet.".format(channel.mention))

    @checks.mod()
    @commands.command(name="mcfcupdate")
    async def update_data(self, ctx):
        async with ctx.typing():
            await self.config.guild_id.set(int(ctx.guild.id))
            self.guild = ctx.guild
            await self.fetch_defaults()
        await ctx.send("Done")

    @tasks.loop(seconds=5.0)
    async def fetch_live_match(self):
        if (await self.config.live_match_id()) != None:
            channel = discord.utils.get(self.guild.channels, id=await self.config.channel_live_id())
            url = "https://api.football-data.org/v2/matches/{}".format(await self.config.live_match_id())
            resp_score, status_score = await self.api_call_paid(url, return_status=True)

            if resp_score["match"]["status"] == "FINISHED":
                if self.message != None:
                    try:
                        await self.message.delete()    
                    except:
                        pass
                embed = discord.Embed(color=discord.Color.blue(), description="Join us on Social Media!")
                embed.add_field(name="The Manchester Discord FC Socials!", value=(
                    "*Twitter* - http://www.twitter.com/mancitydiscord\n" +
                    "*Patreon* - https://www.patreon.com/mancitydiscord\n" +
                    "*Merch* - https://teespring.com/en-GB/stores/manchester-city-fc-discord"
                ))
                await channel.send(embed=embed)
                embed = discord.Embed(color=discord.Color.blue(), description="Match ended!")
                await self.send_commentary(embed=embed)
                await self.append_previous(resp_score)
                await self.config.last_match.set(resp_score)
                await self.reset_live()
                self.fetch_live_match.cancel()

            if status_score == 200:
                if (resp_score != self.plscore):
                    if (resp_score["match"]["status"] == "IN_PLAY") or (resp_score["match"]["status"] == "PAUSED"):
                        self.plscore = resp_score

                        if self.kickoff == False:
                            embed = discord.Embed(color=discord.Color.blue(), description="Match started!")
                            await self.send_commentary(embed=embed)
                            self.kickoff = True

                        updated = await self.commentary(resp_score)

                        if resp_score["match"]["minute"] == "BREAK":
                            resp_score["match"]["minute"] = "Half Time"
                            if self.halftime == False:
                                embed = discord.Embed(color=discord.Color.blue(), description="First half ended!")
                                await self.send_commentary(embed=embed)
                                self.halftime = True

                        if (resp_score["match"]["status"] == "IN_PLAY") and (self.halftime == True) and (self.shalf == False):
                            embed = discord.Embed(color=discord.Color.blue(), description="Second half started!")
                            await self.send_commentary(embed=embed)
                            self.shalf = True                            

                        embed = discord.Embed(color=discord.Color.blue(), description="Live Standings")
                        name = "{}   {} - {}   {}".format(resp_score["match"]["homeTeam"]["name"], resp_score["match"]["score"]["fullTime"]["homeTeam"], resp_score["match"]["score"]["fullTime"]["awayTeam"], resp_score["match"]["awayTeam"]["name"])
                        embed.add_field(name=name, value="Min: " + str(resp_score["match"]["minute"]))

                        if self.message == None:
                            self.message = await channel.send(embed=embed)
                        else:
                            if updated == True:
                                await self.message.delete()
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
        for channel_id in await self.config.channel_commentary_id():
            self.c_messages[channel_id] = None

        if await self.config.time() != None:
            self.start_live.start()

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

    @tasks.loop(seconds=90.0)
    async def get_lineups_elena(self):
        if (await self.config.live_match_id_elena() != None):

            page = 1
            topic = "/fixtures/" + str(await self.config.live_match_id_elena()) + "/lineups?page=" + str(page)
            resp = await self.api_call(topic)

            if resp["data"] != []:
                lineup_total = resp["data"]
                nextPage = resp["pagination"]["hasNextPage"]
                while nextPage == True:
                    await asyncio.sleep(1)
                    page += 1
                    topic = "/fixtures/" + str(await self.config.live_match_id_elena()) + "/lineups?page=" + str(page)
                    resp, status = await self.api_call(topic)
                    if status == 200:
                        nextPage = resp["pagination"]["hasNextPage"]

                        for item in resp["data"]:
                            lineup_total.append(item)

                await self.config.lineup_elena.set(lineup_total)
                filename = "lineup.png"
                filepath = str(cog_data_path(self)) + "/"
                path = str(bundled_data_path(self)) + "/"

                try:
                    pathlib.Path(str(cog_data_path(self)) + "/" + filename).unlink()
                except:
                    pass

                await lineup.create_lineup(lineup_total, path, filepath, filename)
                channel = discord.utils.get(self.guild.channels, id=await self.config.channel_id())
                await channel.send(file=discord.File(str(cog_data_path(self) / filename)))

                self.get_lineups_elena.cancel()

    @tasks.loop(seconds=20.0)
    async def get_lineups(self):
        if (await self.config.live_match_id() != None):
            url = "https://api.football-data.org/v2/matches/{}".format(await self.config.live_match_id())
            resp, status = await self.api_call_paid(url, return_status=True)

            if (resp["match"]["homeTeam"]["lineup"] != []) and (resp["match"]["awayTeam"]["lineup"] != []):
                embed = discord.Embed(color=discord.Color.blue(), description="Lineup for `{}` vs `{}`".format(resp["match"]["homeTeam"]["name"], resp["match"]["awayTeam"]["name"]))
                lp_home = ""
                lp_away = ""
                for i in range(2):
                    if i == 0:
                        gk, df, mf, at = "**Goalkeeper**", "**Defence**", "**Midfield**", "**Attack**"
                        for item in resp["match"]["homeTeam"]["lineup"]:
                            if item["position"] == "Goalkeeper":
                                gk += "\n" + item["name"]
                            elif item["position"] == "Defender":
                                df += "\n" + item["name"]
                            elif item["position"] == "Midfielder":
                                mf += "\n" + item["name"]
                            elif item["position"] == "Attacker":
                                at += "\n" + item["name"]
                        string_home = gk + "\n\n" + df + "\n\n" + mf + "\n\n" + at + "\n\n"
                        
                    else:
                        gk, df, mf, at = "**Goalkeeper**", "**Defence**", "**Midfield**", "**Attack**"
                        for item in resp["match"]["awayTeam"]["lineup"]:
                            if item["position"] == "Goalkeeper":
                                gk += "\n" + item["name"]
                            elif item["position"] == "Defender":
                                df += "\n" + item["name"]
                            elif item["position"] == "Midfielder":
                                mf += "\n" + item["name"]
                            elif item["position"] == "Attacker":
                                at += "\n" + item["name"]
                        string_away = gk + "\n\n" + df + "\n\n" + mf + "\n\n" + at
                embed.add_field(name=resp["match"]["homeTeam"]["name"], value=string_home, inline=True)
                embed.add_field(name=resp["match"]["awayTeam"]["name"], value=string_away, inline=True)
                await self.config.lineup.set(resp["match"])
                await self.send_commentary(embed)
                self.get_lineups.cancel()

    def exception_catching_callback(self, task):
        if task.exception():
            task.print_stack()

    async def match_for_today(self):
        while True:
            now = datetime.datetime.now(pytz.timezone("Europe/London"))
            date = now.date()
            if now.time() > self.time_for_loop:
                date = now.date() + datetime.timedelta(days=1)
            then = datetime.datetime.combine(date, self.time_for_loop)
            await discord.utils.sleep_until(then)

            await self.reset_live()
            channel = discord.utils.get(self.guild.channels, id=await self.config.channel_live_id())
            await channel.purge(limit=100)

            url = "http://api.football-data.org/v2/teams/65/matches?dateFrom={}&dateTo={}".format(str(date), str(date))
            resp, status = await self.api_call_paid(url, return_status=True)
            if status == 200:
                if resp["matches"] != []:
                    date, time = self.convert_time(resp["matches"][0]["utcDate"])
                    embed = discord.Embed(color=discord.Color.blue(), description="Match for today")
                    if resp["matches"][0]["venue"] != None:
                        embed.add_field(name="{} vs. {}".format(resp["matches"][0]["homeTeam"]["name"], resp["matches"][0]["awayTeam"]["name"]), value="{} at {} \n{}".format(date, time, resp["matches"][0]["venue"]))
                    else:
                        embed.add_field(name="{} vs. {}".format(resp["matches"][0]["homeTeam"]["name"], resp["matches"][0]["awayTeam"]["name"]), value="{} at {}".format(date, time))    

                    url = "https://api.football-data.org/v2/matches/{}".format(resp["matches"][0]["id"])
                    resp_match, status = await self.api_call_paid(url, return_status=True)

                    try:
                        h2h = resp_match["head2head"]
                        embed.add_field(name="Head to head statistics", value="Matches: {}\nTotal goals: {}".format(h2h["numberOfMatches"], h2h["totalGoals"]), inline=False)
                        if h2h["homeTeam"]["name"] == "Manchester City FC":
                            embed.add_field(name=h2h["homeTeam"]["name"], value="Wins: {}\nDraws: {}\nLosses: {}".format(h2h["homeTeam"]["wins"], h2h["homeTeam"]["draws"], h2h["homeTeam"]["losses"]), inline=True)
                        else:
                            embed.add_field(name=h2h["awayTeam"]["name"], value="Wins: {}\nDraws: {}\nLosses: {}".format(h2h["awayTeam"]["wins"], h2h["awayTeam"]["draws"], h2h["awayTeam"]["losses"]), inline=True)
                    except:
                        pass

                    embed.set_footer(text="More stats: https://native-stats.org/team/65/stats")
                    embed.set_author(name="Manchester City", icon_url=resp_match["match"]["competition"]["area"]["ensignUrl"])

                    league = resp_match["match"]["competition"]["name"]
                    if league == "Premier League":
                        league = "pl"
                    elif league == "UEFA Champions League":
                        league = "cl"
                    elif league == "FA Cup":
                        league = "fa"

                    await self.config.live_match_id.set(resp["matches"][0]["id"])
                    await channel.send(embed=embed)

                    if league in self.subscribed_leagues:
                        league_id = await self.config_get(league, "season_id_latest")
                        url = "https://football.elenasport.io/v2/seasons/{}/upcoming".format(league_id)
                        resp_elena, status = await self.api_call(api_url=url, return_status=True)
                        if (status == 200) and (resp_elena["data"] != []):
                            for item in resp_elena["data"]:
                                if (item["idHome"] == 99) or (item["idAway"] == 99):
                                    await self.config.live_match_id_elena.set(item["id"])

                    time = resp_match["match"]["utcDate"]
                    await self.config.time.set(time)
                    self.start_live.start()
                    await asyncio.sleep(120)

    @tasks.loop(seconds=10)
    async def start_live(self):
        time = await self.config.time()
        time = self.convert_time(time, return_datetime=True)
        time_lineup = time - datetime.timedelta(hours=1)
        time_live = time - datetime.timedelta(minutes=5)

        date = datetime.datetime.now(time.tzinfo)
        if (date > time_lineup) and (self.get_lineups.is_running() == False) and (await self.config.lineup() == None):
            self.get_lineups.start()
        # if (date > time_lineup) and (self.get_lineups_elena.is_running() == False) and (await self.config.lineup_elena() == None):
        #     self.get_lineups_elena.start()
        if (date > time_live) and (self.fetch_live_match.is_running() == False):
            self.fetch_live_match.start()
        if (await self.config.linuep() != None) and (self.fetch_live_match.is_running() == True):
            self.start_live.cancel()

    # @commands.command()
    # async def temp(self, ctx):
    #     await self.reset_live()
    #     channel = discord.utils.get(self.guild.channels, id=await self.config.channel_live_id())
    #     await channel.purge(limit=100)
    #     date = datetime.datetime.utcnow().date()

    #     url = "http://api.football-data.org/v2/teams/76/matches?dateFrom={}&dateTo={}".format(str(date), str(date))
    #     resp, status = await self.api_call_paid(url, return_status=True)
    #     if status == 200:
    #         if resp["matches"] != []:
    #             date, time = self.convert_time(resp["matches"][0]["utcDate"])
    #             embed = discord.Embed(color=discord.Color.blue(), description="Match for today", url="https://native-stats.org/team/65/stats")
    #             if resp["matches"][0]["venue"] != None:
    #                 embed.add_field(name="{} vs. {}".format(resp["matches"][0]["homeTeam"]["name"], resp["matches"][0]["awayTeam"]["name"]), value="{} at {} \n{}".format(date, time, resp["matches"][0]["venue"]))
    #             else:
    #                 embed.add_field(name="{} vs. {}".format(resp["matches"][0]["homeTeam"]["name"], resp["matches"][0]["awayTeam"]["name"]), value="{} at {}".format(date, time))    

    #             url = "https://api.football-data.org/v2/matches/{}".format(resp["matches"][0]["id"])
    #             resp_match, status = await self.api_call_paid(url, return_status=True)

    #             try:
    #                 h2h = resp_match["head2head"]
    #                 embed.add_field(name="**Head to head statistics**", value="Matches: {}\nTotal goals: {}".format(h2h["numberOfMatches"], h2h["totalGoals"]), inline=False)
    #                 if h2h["homeTeam"]["name"] == "Manchester City FC":
    #                     embed.add_field(name=h2h["homeTeam"]["name"], value="Wins: {}\nDraws: {}\nLosses: {}".format(h2h["homeTeam"]["wins"], h2h["homeTeam"]["draws"], h2h["homeTeam"]["losses"]), inline=True)
    #                 else:
    #                     embed.add_field(name=h2h["awayTeam"]["name"], value="Wins: {}\nDraws: {}\nLosses: {}".format(h2h["awayTeam"]["wins"], h2h["awayTeam"]["draws"], h2h["awayTeam"]["losses"]), inline=True)
    #             except:
    #                 pass

    #             embed.set_footer(text="More stats: https://native-stats.org/team/65/stats")
    #             embed.set_author(name="The Manchester City Discord", icon_url=self.guild.icon_url)
    #             embed.set_thumbnail(url=self.guild.icon_url)
    #             embed.set_image(url=resp_match["match"]["competition"]["area"]["ensignUrl"])

    #             league = resp_match["match"]["competition"]["name"]
    #             if league == "Premier League":
    #                 league = "pl"
    #             elif league == "UEFA Champions League":
    #                 league = "cl"
    #             elif league == "FA Cup":
    #                 league = "fa"

    #             await self.config.live_match_id.set(resp["matches"][0]["id"])
    #             await channel.send(embed=embed)

    #             if league in self.subscribed_leagues:
    #                 league_id = await self.config_get(league, "season_id_latest")
    #                 url = "https://football.elenasport.io/v2/seasons/{}/upcoming".format(league_id)
    #                 resp, status = await self.api_call(api_url=url, return_status=True)
    #                 if (status == 200) and (resp["data"] != []):
    #                     for item in resp["data"]:
    #                         if (item["idHome"] == 99) or (item["idAway"] == 99):
    #                             await self.config.live_match_id_elena.set(item["id"])

    #             time = resp_match["match"]["utcDate"]
    #             await self.config.time.set(time)
    #             self.start_live.start()

    # @commands.command()
    # async def temp2(self, ctx):
    #     print(self.start_live.is_running())
    #     await ctx.send(":goal:")
