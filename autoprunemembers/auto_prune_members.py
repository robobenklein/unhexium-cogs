
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
from datetime import datetime

import discord
from async_timeout import timeout
from discord.ext import tasks
import requests
import aiohttp
import parsedatetime

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

def get_timestamp_seconds():
    ts = time.time()
    return int(ts)

def human_timestr_to_timedelta(usertime):
    c=parsedatetime.Calendar()
    return c.parseDT(usertime, sourceTime=datetime.min)[0] - datetime.min


class AutoPruneMembers(commands.Cog):

    default_global = {}
    default_guild = {
        # "roleless_members": {},
        "target_channel": None,
        "timeout_secs": 24*60*60,
    }
    default_channel = {
        # "pending_requests": [],
    }
    default_member = {
        "first_seen_ts": None,
    }

    def __init__(self, bot: Red):
        self.bot = bot

        self.config = Config.get_conf(self, identifier=65498813227)

        self.config.register_global(**self.default_global)
        self.config.register_guild(**self.default_guild)
        self.config.register_channel(**self.default_channel)
        self.config.register_member(**self.default_member)

        self.auto_prune_task.start()

    def cog_unload(self):
        self.auto_prune_task.cancel()

    def cog_check(self, ctx: commands.Context):
        if not ctx.guild:
            raise commands.NoPrivateMessage('This command can\'t be used in DM channels.')

        return True

    async def cog_before_invoke(self, ctx: commands.Context):
        ctx.cfg_guild = self.config.guild(ctx.guild)
        ctx.cfg_channel = self.config.channel(ctx.channel)
        ctx.cfg_member = self.config.member(ctx.author)

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        print(f"cog_command_error handling error {type(error)}: {error}")
        if isinstance(error, commands.MissingPermissions):
            await ctx.send('Missing required permission. Ensure bot has all permissions needed to do it\'s job.')
        else:
            await ctx.send('An unknown error occurred, please report this: {}'.format(str(error)))
            raise error

    ### NOTE Commands

    @commands.group(name='autoprune', aliases=["ap", "autokick"])
    async def ap(self, ctx: commands.Context):
        """Base command for AutoPruneMembers"""
        pass

    @ap.command(name="setchannel", aliases=["setch"])
    @commands.admin()
    async def set_logging_channel(self, ctx, channel: discord.TextChannel = None):
        """Enable or disable the auto-pruning of members by setting the channel to report to.

        Unset the channel (and disable the auto-prune) by just running this command with no arguments.
        """
        # channels = await ctx.cfg_guild.requestchannels()
        if channel is None:
            await ctx.cfg_guild.target_channel.set(None)
            return await ctx.reply(f"Cleared the auto-prune report channel. Auto-prune kicking now disabled.")
        await ctx.cfg_guild.target_channel.set(channel.id)
        return await ctx.reply(f"Now reporting auto-pruning kicks in {channel.mention}.")

    @ap.command(name="settimeout", aliases=["settime", "time"])
    @commands.admin()
    async def set_autoprune_timeout(self, ctx, time_amount: str = None):
        """Set how long a user should be kicked after if they have no roles.

        Default is "24hrs", specify any time interval, such as "1week" or "2 hours"
        """
        if not time_amount:
            seconds = await ctx.cfg_guild.timeout_secs()
            return await ctx.reply(f"User pruning timeout is currently set to {seconds} seconds.")
        seconds = int(human_timestr_to_timedelta(time_amount).total_seconds())
        await ctx.cfg_guild.timeout_secs.set(seconds)
        return await ctx.reply(f"Set user pruning timeout to {seconds} seconds.")

    ### Task

    @tasks.loop(seconds=79.0)
    async def auto_prune_task(self):
        for guild in self.bot.guilds:
            # print(f"Checking autoprune for guild {guild.name}")
            cfg_guild = self.config.guild(guild)
            channel_id = await cfg_guild.target_channel()
            if not channel_id:
                # print(f"Autoprune NOT enabled for guild {guild.name}")
                continue
            channel = guild.get_channel(channel_id)

            timeout_secs = await cfg_guild.timeout_secs()
            # print(f"Guild {guild.name} timeout set to {timeout_secs} seconds.")

            errors = []
            for member in guild.members:
                if member.bot:
                    continue
                if len(member.roles) > 1: # first role is "@everyone"
                    # print(f"User {member.name} has roles... skipping.")
                    continue
                print(f"Checking roleless member {member.name} for auto-prune...")
                cfg_member = self.config.member(member)
                async with cfg_member.all() as mcfg:
                    if not mcfg["first_seen_ts"]:
                        mcfg["first_seen_ts"] = get_timestamp_seconds()
                        print(f"Saw {member.name} for the first time at {mcfg['first_seen_ts']}")
                        continue
                    if (get_timestamp_seconds() - timeout_secs) > mcfg["first_seen_ts"]:
                        try:
                            await member.kick()
                            del mcfg["first_seen_ts"]
                            print(f"Kicked roleless member {member.name} for auto-prune.")
                            await channel.send(f"Kicked {member.mention} (id {member.id})")
                        except Exception as e:
                            errors.append(e)

            if errors:
                await channel.send(f"One or more errors encountered during auto-prune of guild members.")
                raise errors[0]

    @auto_prune_task.before_loop
    async def wait_for_bot_ready_before_task(self):
        await self.bot.wait_until_ready()
