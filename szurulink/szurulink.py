
import asyncio
import functools
import itertools
import math
import random
import re
import base64
from io import BytesIO

import discord
from async_timeout import timeout
# from discord.ext import commands
import requests
import aiohttp

from redbot.core import commands
from redbot.core import Config, commands, checks
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import pagify, warning
from redbot.core.i18n import Translator


def stringToBase64(s):
    return base64.b64encode(s.encode('utf-8')).decode('utf-8')

def base64ToString(b):
    return base64.b64decode(b).decode('utf-8')


class SzuruPoster(commands.Cog):

    default_guild = {
        "channel": None,
    }
    default_channel = {
        "time": {
            "minutes": 60,
        },
        "api_url": None,
        "api_token": None,
        "api_user": None,
        "current_post_num": 0,
    }
    default_member = {
        "szuruname": None
    }

    def __init__(self, bot: Red):
        self.bot = bot

        self.config = Config.get_conf(self, identifier=435619873)
        self.session = aiohttp.ClientSession(loop=bot.loop)

        self.config.register_guild(**self.default_guild)
        self.config.register_channel(**self.default_channel)
        self.config.register_member(**self.default_member)

    # def cog_unload(self):
    #     for state in self.voice_states.values():
    #         self.bot.loop.create_task(state.stop())
    #
    #     return state

    def cog_check(self, ctx: commands.Context):
        if not ctx.guild:
            raise commands.NoPrivateMessage('This command can\'t be used in DM channels.')

        return True

    async def cog_before_invoke(self, ctx: commands.Context):
        ctx.cfg_guild = self.config.guild(ctx.guild)
        ctx.cfg_channel = self.config.channel(ctx.channel)

    # async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
    #     if isinstance(error, commands.MissingPermissions):
    #         await ctx.send('Music: do you have permission to do that?')
    #     else:
    #         await ctx.send('Music: An error occurred: {}'.format(str(error)))

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
        unsafe = True if data['safety'] == "unsafe" else False
        data['_'] = {
            "link": f"{cu}/{data['contentUrl']}",
            "unsafe": unsafe,
            "filename": data['contentUrl'].split('/')[-1],
            "user": {
                "icon_url": f"{cu}/{data['user']['avatarUrl']}",
                "name": data['user']['name'],
                "url": f"{cu}/user/{data['user']['name']}",
            },
        }
        return data

    async def post_data_to_embed(self, data):
        embed = discord.Embed(
            title=f"Post {data['id']}",
            url=data['_']['link'],
            description="TODO",
        )
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
        else:
            api_token = await ctx.cfg_channel.api_token()
            await ctx.send(f"Token is {len(api_token)} characters.")

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

    # @commands.Cog.listener('on_message')
    # async def on_message(self, message):
    #     if message.content in e_qs.keys():
    #         await message.reply(e_qs[message.content])
