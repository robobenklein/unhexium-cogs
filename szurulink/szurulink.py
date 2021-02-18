
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

import discord
from async_timeout import timeout
from discord.ext import tasks
import requests
import aiohttp

from redbot.core import commands
from redbot.core import Config, commands, checks
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import pagify, warning
from redbot.core.i18n import Translator

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


class SzuruPoster(commands.Cog):

    default_global = {
        "autoposttimer": 10,
    }
    default_guild = {
        "autopostchannel": None,
        "autopostseconds": 3600,
    }
    default_channel = {
        "time": {
            "minutes": 60,
        },
        "api_url": None,
        "api_token": None,
        "api_user": None,
        "current_post_num": 0,
        "last_post_time": 0,
    }
    default_member = {
        "szuruname": None
    }

    def __init__(self, bot: Red):
        self.bot = bot

        self.config = Config.get_conf(self, identifier=435619873)
        self.session = aiohttp.ClientSession(loop=bot.loop)

        self.config.register_global(**self.default_global)
        self.config.register_guild(**self.default_guild)
        self.config.register_channel(**self.default_channel)
        self.config.register_member(**self.default_member)

        self.check_send_next_post.start()

    # def cog_unload(self):
    #     for state in self.voice_states.values():
    #         self.bot.loop.create_task(state.stop())
    #
    #     return state

    def cog_unload(self):
        self.check_send_next_post.cancel()

    def cog_check(self, ctx: commands.Context):
        if not ctx.guild:
            raise commands.NoPrivateMessage('This command can\'t be used in DM channels.')

        return True

    async def cog_before_invoke(self, ctx: commands.Context):
        ctx.cfg_guild = self.config.guild(ctx.guild)
        ctx.cfg_channel = self.config.channel(ctx.channel)

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send('SzuruLink: do you have permission to do that?')
        else:
            await ctx.send('SzuruLink: An error occurred: {}'.format(str(error)))
            raise error

    async def get_url_file_buffer(self, url):
        resp = await self.session.get(url)
        try:
            content = await resp.read()
        finally:
            resp.close()
        buffer = BytesIO(content)
        return buffer

    async def get_file_from_post_data(self, data):
        attach = discord.File(
            await self.get_url_file_buffer(data['_']['link']),
            filename=data['_']['filename'],
            spoiler=data['_']['unsafe'],
        )
        return attach

    async def get_api_url(self, ctx: commands.Context):
        cu = await ctx.cfg_channel.api_url()
        return f"{cu}/api"

    async def api_get(self, ctx: commands.Context, path):
        au = await self.get_api_url(ctx)
        api_user = await ctx.cfg_channel.api_user()
        api_token = await ctx.cfg_channel.api_token()
        auth = stringToBase64(f"{api_user}:{api_token}")

        r = requests.get(
            f"{au}{path}",
            headers={
                'Authorization': f"Token {auth}",
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            }
        )
        return r.json()

    async def get_post_by_id(self, ctx: commands.Context, postid):
        cu = await ctx.cfg_channel.api_url()
        data = await self.api_get(ctx, f"/post/{postid}")
        if 'name' in data and data['name'] == 'PostNotFoundError':
            raise LookupError(f"No such post with ID {postid}")
        unsafe = True if data['safety'] == "unsafe" else False

        data['_'] = {
            "link": f"{cu}/{data['contentUrl']}",
            "unsafe": unsafe,
            "filename": data['contentUrl'].split('/')[-1],
            "user": None
        }
        if 'user' in data and data['user']:
            data['_']["user"] = {
                "icon_url": f"{cu}/{data['user']['avatarUrl']}",
                "name": data['user']['name'],
                "url": f"{cu}/user/{data['user']['name']}",
            }
        return data

    async def post_data_to_embed(self, data):
        embed = discord.Embed(
            title=f"Post {data['id']}",
            url=data['_']['link'],
            description="TODO",
        )
        if data['_']['user']:
            embed.set_author(**data['_']['user'])
        return embed

    ### NOTE Commands

    @commands.group(name='szuru', aliases=["sz"])
    async def szuru(self, ctx: commands.Context):
        """Base command for SzuruLink"""
        pass

    @szuru.group(name='set', aliases=["s"])
    @commands.admin()
    async def szuru_set(self, ctx: commands.Context):
        """SzuruLink settings"""
        pass

    @szuru_set.command(name='url')
    async def set_api_url(self, ctx: commands.Context, *, api_url: str = None):
        if api_url:
            await ctx.cfg_channel.api_url.set(api_url)
            await ctx.send(f"Set API URL to {api_url}")
        else:
            api_url = await ctx.cfg_channel.api_url()
            await ctx.send(f"API URL is {api_url}")

    @szuru_set.command(name='user')
    async def set_api_user(self, ctx: commands.Context, *, api_user: str = None):
        if api_user:
            await ctx.cfg_channel.api_user.set(api_user)
            await ctx.send(f"Set API user to {api_user}")
        else:
            api_user = await ctx.cfg_channel.api_user()
            await ctx.send(f"API user is {api_user}")

    @szuru_set.command(name='token')
    async def set_api_token(self, ctx: commands.Context, *, token: str = None):
        if token:
            await ctx.cfg_channel.api_token.set(token)
            await ctx.send(f"Set token.")
            await ctx.message.delete()
        else:
            api_token = await ctx.cfg_channel.api_token()
            await ctx.send(f"Token is {len(api_token)} characters.")

    @szuru_set.command(name='channel', aliases=['ch'])
    async def set_channel(self, ctx: commands.Context, channel: discord.TextChannel = None):
        """
        Set the channel for auto-posting new szuru posts
        """
        if channel is not None:
            await self.config.guild(ctx.guild).autopostchannel.set(channel.id)
            await ctx.send("Auto-post channel has been set to {}".format(channel.mention))
        else:
            await self.config.guild(ctx.guild).autopostchannel.set(None)
            await ctx.send("Auto-post channel has been cleared")

    @szuru_set.command(name='time', aliases=['seconds'])
    async def set_timer(self, ctx: commands.Context, seconds: int = None):
        """
        Set how often to send new posts, please do not set faster than 60 seconds.
        """
        if seconds is not None:
            await ctx.cfg_guild.autopostseconds.set(seconds)
            await ctx.send("Auto-post timer has been set to {}".format(seconds))
        else:
            seconds = await ctx.cfg_guild.autopostseconds()
            await ctx.send(f"Currently posting every {seconds} seconds.")

    @szuru.command(name='post', aliases=['p'])
    async def get_post(self, ctx: commands.Context, postid: int):
        async with ctx.typing():
            data = await self.get_post_by_id(ctx, postid)
            post_e = await self.post_data_to_embed(data)
            attach = await self.get_file_from_post_data(data)

            await ctx.send(
                embed=post_e,
                file=attach,
            )

    ### Task

    @tasks.loop(seconds=37.0)
    async def check_send_next_post(self):
        for guild in self.bot.guilds:
            cfg_guild = self.config.guild(guild)
            channel = await cfg_guild.autopostchannel()
            if channel is None:
                continue
            ch = guild.get_channel(channel)
            if ch is None:
                print(f"channel was deleted? {guild}: {channel}")
                owner = guild.owner
                await self.bot.send_message(owner, f"SzuruLink: Lost track of {guild}: channel {channel}")
                await cfg_guild.autopostchannel.set(None)
                continue

            cfg_channel = self.config.channel(ch)
            last_post_id = await cfg_channel.current_post_num()
            last_post_time = await cfg_channel.last_post_time()
            autopostseconds = await cfg_guild.autopostseconds()
            now = get_timestamp_seconds()

            if now < last_post_time + autopostseconds:
                continue

            await cfg_channel.last_post_time.set(now)

            ctx = dotdict()
            ctx.cfg_channel = cfg_channel
            ctx.cfg_guild = cfg_guild
            try:
                data = await self.get_post_by_id(ctx, last_post_id + 1)
                post_e = await self.post_data_to_embed(data)
                attach = await self.get_file_from_post_data(data)
                await ch.send(
                    # f"Next Szuru Post:",
                    embed=post_e,
                    file=attach,
                )
                await cfg_channel.current_post_num.set(last_post_id + 1)
            except LookupError as e:
                continue

    @check_send_next_post.before_loop
    async def check_send_next_post_wait(self):
        await self.bot.wait_until_ready()

    # @commands.Cog.listener('on_message')
    # async def on_message(self, message):
    #     if message.content in e_qs.keys():
    #         await message.reply(e_qs[message.content])
