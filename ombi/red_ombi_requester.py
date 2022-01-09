
import asyncio
import functools
import itertools
import math
import random
import re
import base64
import asyncio
import time
from io import BytesIO
import urllib
import json
from collections.abc import Iterable

import discord
from async_timeout import timeout
from discord.ext import tasks
import requests
import aiohttp

from redbot.core import commands
from redbot.core import Config, commands, checks
from redbot.core.bot import Red
from redbot.core.utils import chat_formatting, menus
from redbot.core.utils.chat_formatting import pagify, warning, box, spoiler, escape
from redbot.core.i18n import Translator
from redbot.vendored.discord.ext import menus

class dotdict(dict):
    """dot.notation access to dictionary attributes"""
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__

def stringToBase64(s):
    return base64.b64encode(s.encode('utf-8')).decode('utf-8')

def base64ToString(b):
    return base64.b64decode(b).decode('utf-8')

def get_timestamp_seconds():
    ts = time.time()
    return int(ts)

POSTER_URL_BASE = "https://image.tmdb.org/t/p/w300"


class EntrySelectMenu(menus.MenuPages):
    def __init__(self, source, **kwargs):
        super().__init__(source, timeout=300.0, delete_message_after=True, **kwargs)

        self.selected = None
        self.index = None

    async def finalize(self, timed_out):
        if not timed_out:
            self.selected = self._source.entries[self.current_page]

    async def prompt(self, ctx):
        await self.start(ctx, wait=True)
        # return self._source.entries[self.current_page]
        return self.selected

class EntryEmbedPageSource(menus.ListPageSource):
    def __init__(self, data):
        super().__init__(data, per_page=1)
        print(f"EntryEmbedPageSource constructed with {len(data)} items")

    async def entry_data_to_embed(self, data, *, include_image=True):
        embed = discord.Embed(
            title=data["title"],
            description=data["overview"],
        )

        if include_image:
            embed.set_image(url=f"{POSTER_URL_BASE}/{data['poster']}")

        return {
            "content": "Select the desired result, then press the stop button.",
            "embed": embed,
        }

    async def format_page(self, menu, entry):
        offset = menu.current_page
        # print(f"offset {offset}, entries {entries}, self.entries {self.entries}")
        embed = await self.entry_data_to_embed(entry)
        return embed

class RedOmbiRequester(commands.Cog):

    default_global = {}
    default_guild = {
        "requestchannels": [],
    }
    default_channel = {}
    default_member = {
        "requests": [],
    }

    def __init__(self, bot: Red):
        self.bot = bot

        self.config = Config.get_conf(self, identifier=46216399787)
        self.session = aiohttp.ClientSession(
            loop=bot.loop,
            raise_for_status=False
        )

        self.config.register_global(**self.default_global)
        self.config.register_guild(**self.default_guild)
        self.config.register_channel(**self.default_channel)
        self.config.register_member(**self.default_member)

    def cog_unload(self):
        self.bot.loop.run_until_complete(
            self.session.close()
        )

    def cog_check(self, ctx: commands.Context):
        if not ctx.guild:
            raise commands.NoPrivateMessage('This command can\'t be used in DM channels.')

        return True

    async def cog_before_invoke(self, ctx: commands.Context):
        ctx.cfg_guild = self.config.guild(ctx.guild)
        ctx.cfg_channel = self.config.channel(ctx.channel)
        ctx.cfg_member = self.config.member(ctx.author)

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        print(f"ror: handling error {type(error)}: {error}")
        if isinstance(error, commands.MissingPermissions):
            await ctx.send('ROR: do you have permission to do that?')
        elif isinstance(error, aiohttp.client_exceptions.ClientResponseError):
            await ctx.send(f'ROR: server error: {error}')
            print(f"error {error}")
            print(f"request: {error.request_info}")
            # print(f"")
            raise error
        else:
            await ctx.send('ROR: An error occurred: {}'.format(str(error)))
            raise error

    async def get_url_file_buffer(self, url):
        resp = await self.session.get(url)
        try:
            content = await resp.read()
        finally:
            resp.close()
        buffer = BytesIO(content)
        return buffer

    async def get_api_url(self, ctx: commands.Context):
        ombi_api = await self.bot.get_shared_api_tokens("ombi")
        if ombi_api.get("url") is None:
            await ctx.send(f"The Ombi URL for this bot has not been set.")
            return None
        if ombi_api.get("apikey") is None:
            await ctx.send(f"The Ombi API Key for this bot has not been set.")
            return None
        cu = ombi_api.get("url")
        return f"{cu}/api"

    async def api_get(self, ctx: commands.Context, path):
        au = await self.get_api_url(ctx)
        if not au:
            raise ValueError("There's no API URL set for this channel!")
        ombi_api = await self.bot.get_shared_api_tokens("ombi")
        api_key = ombi_api.get("apikey")

        r = await self.session.get(
            f"{au}{path}",
            headers={
                'ApiKey': api_key,
                # 'Content-Type': 'application/json',
                'Accept': 'application/json',
            }
        )
        try:
            return await r.json()
        except json.decoder.JSONDecodeError as e:
            print(f"error: {r}: {e}")
            print(r.text)
            raise RuntimeError("Failed to parse response from server.")

    async def api_post(self, ctx, path, *, json_data = {}):
        au = await self.get_api_url(ctx)
        ombi_api = await self.bot.get_shared_api_tokens("ombi")
        api_key = ombi_api.get("apikey")
        if not api_key:
            raise RuntimeError("Ombi apikey not set")

        print(f"posting to URL {au}{path}")
        r = await self.session.post(
            f"{au}{path}",
            headers={
                'ApiKey': api_key,
                # 'Content-Type': 'application/json',
                'Accept': 'application/json',
            },
            json=json_data,
        )
        try:
            # print(f"resp {r} {r.status}:")
            # print(f"req {r.request_info}")
            # print(await r.text())
            return await r.json()
        except json.decoder.JSONDecodeError as e:
            print(f"error: {r}: {e}")
            print(r.text)
            raise RuntimeError("Failed to parse response from server.")

    async def get_movies_by_query(self, ctx, user_query: str):
        query_param = urllib.parse.quote(user_query.encode('utf8'))
        results = await self.api_post(
            ctx, f"/v2/Search/multi/{query_param}",
            json_data={
                "movies": True,
            }
        )

        return results

    async def get_shows_by_query(self, ctx, user_query: str):
        query_param = urllib.parse.quote(user_query.encode('utf8'))
        results = await self.api_post(
            ctx, f"/v2/Search/multi/{query_param}",
            json_data={
                "tvShows": True,
            }
        )

        return results

    async def entry_data_to_embed(self, data, *, include_image=True):
        embed = discord.Embed(
            title=data["title"],
            description=data["overview"],
        )

        # TODO exposing URL of ombi instance with poster?
        if include_image:
            embed.set_image(url=f"{POSTER_URL_BASE}/{data['poster']}")

        return embed

    async def select_entry_menu(
            self, ctx, entries, send_selection_confirmation=True,
        ):
        pages = EntrySelectMenu(
            source=EntryEmbedPageSource(entries),
            clear_reactions_after=True,
        )
        selected = await pages.prompt(ctx)

        if selected is None:
            await ctx.send(f"Selection timed out.")
            return None

        if send_selection_confirmation:
            entry_embed = await self.entry_data_to_embed(selected)
            await ctx.send("Selected:", embed=entry_embed)

        return selected

    # missing self but not "staticmethod"
    async def assert_is_request_channel(self, ctx):
        channels = await ctx.cfg_guild.requestchannels()
        if not channels:
            assert ctx.channel.id in channels, f"There aren't currently any channels enabled to take requests. Ask an admin to add one."
        assert ctx.channel.id in channels, f"Requests are not allowed in this channel."

    ### NOTE Commands

    @commands.group(name='ombi', aliases=["ror"])
    async def ror(self, ctx: commands.Context):
        """Base command for RedOmbiRequester"""
        pass

    @ror.command(name="addchannel", aliases=["addch"])
    @commands.admin()
    async def ror_add_request_channel(self, ctx, channel: discord.TextChannel):
        """Enable requests within a channel"""
        channels = await ctx.cfg_guild.requestchannels()
        if channels is None:
            channels = []
        channels.append(channel.id)
        await ctx.cfg_guild.requestchannels.set(channels)
        await ctx.reply(f"Now allowing requests in channel {channel.mention}")

    @ror.command(name="removechannel", aliases=["rmch", "delch"])
    @commands.admin()
    async def ror_remove_request_channel(self, ctx, channel: discord.TextChannel):
        """Disable requests within a channel"""
        channels = await ctx.cfg_guild.requestchannels()
        if channels is None:
            channels = []
        if channel.id not in channels:
            return await ctx.reply(f"That channel is not currently accepting requests.")
        channels.remove(channel.id)
        await ctx.cfg_guild.requestchannels.set(channels)
        await ctx.reply(f"Stopped allowing requests in channel {channel.mention}")

    @commands.command(name='movie')
    async def request_movie(self, ctx: commands.Context, *search: str):
        """Search for a movie to request"""
        await self.assert_is_request_channel(ctx)
        if not search:
            return await ctx.send_help()
        results = await self.get_movies_by_query(ctx, " ".join(search))

        if not results:
            await ctx.reply(f"I couldn't find anything matching that search!")
            return

        selected = await self.select_entry_menu(ctx, results)
        if selected is None:
            return

        req_res = await self.api_post(
            ctx, "/v1/Request/movie",
            json_data={
                "theMovieDbId": selected["id"],
                "requestedByAlias": ctx.author.name,
            }
        )

        if req_res["result"]:
            await ctx.send(f"Request sent successfully! {req_res['message']}")
        elif req_res["errorCode"] == "AlreadyRequested":
            await ctx.send(f"The request already exists! {req_res['errorMessage']}")
        elif req_res["isError"] and req_res["errorCode"] is None:
            await ctx.send(f"{req_res['errorMessage']}")
        elif "errorCode" in req_res:
            await ctx.send(f"Something went wrong... pls report this error: {req_res['errorCode']}")
            print(f"HALP! {req_res}")
        else:
            await ctx.send(f"Something went wrong... pls report this error!")
            print(f"HALP! {req_res}")

    @commands.command(name='tv')
    async def request_tv(self, ctx: commands.Context, *search: str):
        """Search for a TV show to request"""
        await self.assert_is_request_channel(ctx)
        if not search:
            return await ctx.send_help()
        results = await self.get_shows_by_query(ctx, " ".join(search))

        if not results:
            await ctx.reply(f"I couldn't find anything matching that search!")
            return

        selected = await self.select_entry_menu(ctx, results)
        if selected is None:
            return

        show_id = selected["id"]
        show_info = await self.api_get(
            ctx, f"/v2/Search/tv/{show_id}",
        )
        requestable_seasons = []
        for season_req in show_info["seasonRequests"]:
            requestable_seasons.append(season_req["seasonNumber"])

        # ask for a season number to fetch
        def check(msg):
            if msg.channel != ctx.channel:
                return False
            elif msg.author != ctx.author:
                return False
            try:
                num = int(msg.content)
                return True
            except ValueError:
                return False
        try:
            await ctx.send(f"Which season? Options: {requestable_seasons}")
            msg = await self.bot.wait_for("message", timeout=30, check=check)
            season_num = int(msg.content)
        except asyncio.TimeoutError:
            await ctx.send("Season selection timed out.")
            return

        req_res = await self.api_post(
            ctx, "/v2/Requests/tv",
            json_data={
                "theMovieDbId": selected["id"],
                "requestedByAlias": ctx.author.name,
                "requestAll": False,
                "latestSeason": False,
                "firstSeason": False,
                "seasons": [
                    {
                        "seasonNumber": season_num,
                    }
                ],
            }
        )

        print(f"tv request response: {req_res}")
        if req_res["result"]:
            await ctx.send(f"Request sent successfully!")
        elif req_res["errorCode"] == "AlreadyRequested":
            await ctx.send(f"Looks like it's already been requested! {req_res['errorMessage']}")
        elif req_res["isError"] and req_res["errorCode"] is None:
            await ctx.send(f"{req_res['errorMessage']}")
        elif "errorCode" in req_res:
            await ctx.send(f"Something went wrong... pls report this error: {req_res['errorCode']}")
            print(f"HALP! {req_res}")
        else:
            await ctx.send(f"Something went wrong... pls report this error!")
            print(f"HALP! {req_res}")
