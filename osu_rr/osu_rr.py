
import asyncio
import functools
import itertools
import math
import random
import re
import base64
import asyncio
import time
import urllib
import json

import discord
from async_timeout import timeout
from discord.ext import tasks
from discord.ext.commands import BucketType
import requests
import aiohttp
from tenacity import retry
from tenacity.stop import stop_after_attempt
from tenacity.wait import wait_random
from tenacity.retry import retry_if_exception_type

from redbot.core import commands
from redbot.core import Config, commands, checks
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import pagify, warning, box, spoiler, escape
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

round_to_n = lambda x, n: x if x == 0 else round(x, -int(math.floor(math.log10(abs(x)))) + (n - 1))
def display_number(n: int) -> str:
    if type(n) is not int:
        return str(n)
    suffix = 0
    suffixes = ["", "K", "M", "B"]
    while n >= 1000:
        n /= 1000
        suffix += 1
    n = str(n)
    if '.' in n:
        gt1, lt1 = n.split('.')
        n = gt1
        rd_ta = max(3 - len(gt1), 0)
        if rd_ta:
            n += f".{lt1[:rd_ta]}"

    return f"{n}{suffixes[suffix]}"

osu_base_url = "https://osu.ppy.sh"
osu_api = f"{osu_base_url}/api/v2"
# api_ratelimit_minute = 60


class OsuRankReporter(commands.Cog):

    default_global = {
        "users_updated_per_minute": 10,
    }
    default_guild = {
        "autopostchannel": None,
        "autopostseconds": 3600,
        "char_pre": "(",
        "char_post": ")",
    }
    # default_channel = {
    #     "time": {
    #         "minutes": 60,
    #     },
    #     "api_url": None,
    #     "api_token": None,
    #     "api_user": None,
    #     "current_post_num": 0,
    #     "last_post_time": 0,
    # }
    default_member = {
        "state": None,
        "last_rank": None,
        "osu_id": None, # int
        "last_update": 0, # seconds timestamp
    }

    def __init__(self, bot: Red):
        self.bot = bot

        self.config = Config.get_conf(self, identifier=109834676)
        self.session = aiohttp.ClientSession(
            loop=bot.loop,
            raise_for_status=False,
            timeout=aiohttp.ClientTimeout(total=30),
        )

        self.config.register_global(**self.default_global)
        self.config.register_guild(**self.default_guild)
        # self.config.register_channel(**self.default_channel)
        self.config.register_member(**self.default_member)

        self.rank_update_loop.start()

        self.cur_token = None
        self.cur_token_expiry = get_timestamp_seconds() - 10 # in the past

    # def cog_unload(self):
    #     for state in self.voice_states.values():
    #         self.bot.loop.create_task(state.stop())
    #
    #     return state

    def cog_unload(self):
        self.rank_update_loop.cancel()
        self.bot.loop.run_until_complete(
            self.session.close()
        )

    def cog_check(self, ctx: commands.Context):
        if not ctx.guild:
            raise commands.NoPrivateMessage('This command can\'t be used in DM channels.')

        return True

    # async def check_user_authenticated(self, ctx):
    # async def check_channel_initialized(self, ctx):

    async def cog_before_invoke(self, ctx: commands.Context):
        ctx.cfg_guild = self.config.guild(ctx.guild)
        ctx.cfg_channel = self.config.channel(ctx.channel)
        ctx.cfg_member = self.config.member(ctx.author)

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send('osu!rr: do you have permission to do that?')
        elif isinstance(error, aiohttp.client_exceptions.ClientResponseError):
            await ctx.send(f'osu!rr: server error: {error}')
            print(f"error {error}")
            print(f"request: {error.request_info}")
            raise error
        else:
            await ctx.send('osu!rr: An error occurred: {}'.format(str(error)))
            raise error

    async def get_auth_bearer_public(self):
        osu_keys = await self.bot.get_shared_api_tokens("osu")
        if (client_id := osu_keys.get("client_id")) is None:
            raise ValueError(f"Bot setup is incomplete, please set the osu API client_id")
        if (client_secret := osu_keys.get("client_secret")) is None:
            raise ValueError(f"Bot setup is incomplete, please set the osu API client_secret")

        if get_timestamp_seconds() >= self.cur_token_expiry:
            # request a new token:
            _r = await self.session.post(
                f"{osu_base_url}/oauth/token",
                json={
                    "scope": "public",
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                }
            )
            try:
                new_tok = json.loads(await _r.text())
            except json.decoder.JSONDecodeError as e:
                print(f"Failed to decode: {await _r.text()}")
                raise e
            self.cur_token = new_tok["access_token"]
            self.cur_token_expiry = get_timestamp_seconds() + new_tok["expires_in"] - 10

        return f"Bearer {self.cur_token}"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_random(min=2, max=5),
        retry=retry_if_exception_type(asyncio.exceptions.TimeoutError),
        reraise=True,
    )
    async def api_get(self, ctx: commands.Context, path):
        auth = await self.get_auth_bearer_public()

        print(f"GET {osu_api}{path}")
        r = await self.session.get(
            f"{osu_api}{path}",
            headers={
                'Authorization': auth,
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            }
        )
        # print(f"GET {osu_api}{path}")
        try:
            return json.loads(await r.text())
        except json.decoder.JSONDecodeError as e:
            print(f"error: {r}: {e}")
            print(r.text)
            raise RuntimeError("Failed to parse response from server.")

    async def get_user_by_id(self, ctx: commands.Context, user_id: int, mode="osu"):
        data = await self.api_get(ctx, f"/users/{user_id}/{mode}?key=id")

        if 'username' not in data:
            raise LookupError(f"Does that user exist?")

        return data

    async def get_user_by_username(self, ctx: commands.Context, username: str, mode="osu"):
        data = await self.api_get(ctx, f"/users/{username}/{mode}?key=username")

        if 'username' not in data:
            raise LookupError(f"Didn't find that user.")

        return data

    async def user_data_to_embed(self, data, *, include_image=True):
        embed = discord.Embed(
            title=f"osu! {data['username']}",
            url=f"{osu_base_url}/users/{data['id']}",
            # color=data['profile_colour'],
        )
        if data['avatar_url']:
            embed.set_author(
                name=data['username'],
                url=f"{osu_base_url}/users/{data['id']}",
                icon_url=data['avatar_url'],
            )
        # if include_image:
        #     embed.set_image(url=data['_']['media_url'])
        if 'country' in data:
            embed.add_field(
                name="Country",
                value=escape(data['country']['name'], formatting=True),
                inline=True,
            )
        if data['statistics']:
            embed.add_field(
                name="Global Rank",
                value=data['statistics']['global_rank'],
                inline=True,
            )
        if data['follower_count']:
            embed.add_field(
                name="Followers",
                value=data['follower_count'],
                inline=True,
            )
        if data['is_supporter']:
            embed.add_field(
                name="Supporter!",
                value="Thanks for supporting osu!",
                inline=True,
            )
        elif data['has_supported']:
            embed.add_field(
                name="Past supporter!",
                value="Thanks for supporting osu!",
                inline=True,
            )
        if data['playmode']:
            embed.add_field(
                name="Primary Mode",
                value=data['playmode'],
                inline=True,
            )
        if data['playstyle']:
            embed.add_field(
                name="Playstyle",
                value=', '.join(data['playstyle']),
                inline=True,
            )
        if data['statistics']['pp']:
            embed.add_field(
                name="Performance",
                value=display_number(data['statistics']['pp']),
                inline=True,
            )

        return embed

    async def update_user_nickname_with_rank(self, ctx, member: discord.Member):
        cur_nickname = member.display_name
        cfg_member = self.config.member(member)
        if (osu_id := await cfg_member.osu_id()) is None:
            print(f"Member {member.display_name} is not linked to an osu! profile")
            return

        char_pre = await ctx.cfg_guild.char_pre()
        char_post = await ctx.cfg_guild.char_post()
        osu_user = await self.get_user_by_id(ctx, osu_id)
        display_num = display_number(osu_user['statistics']['global_rank'])

        split_left = cur_nickname.rsplit(char_pre, 1)
        if len(split_left) > 1:
            # already has a tag?
            newnick = f"{split_left[0]}{char_pre}{display_num}{char_post}"
        else:
            newnick = f"{split_left} {char_pre}{display_num}{char_post}"

        await member.edit(
            nick=newnick,
        )
        await cfg_member.last_update.set(get_timestamp_seconds())
        return newnick

    ### NOTE Commands

    @commands.group(name='osu', aliases=[])
    async def osu(self, ctx: commands.Context):
        """Base command for osu!rr"""
        pass

    @osu.command(name='register', aliases=[])
    @commands.has_guild_permissions(administrator=True)
    async def user_registration_process(self, ctx: commands.Context, user_mention: str, osu_username: str):
        """I only track the ranks of players who have been registered!
        """
        members = [m for m in ctx.message.mentions if not m.bot]
        if 0 == len(members) > 1:
            await ctx.send(f"Please only mention one user at a time!")
            return
        if not osu_username:
            await ctx.send(f"Please specify the osu! profile to link to")
            return
        if osu_username.isdigit():
            osu_id = int(osu_username)
        else:
            osu_user = await self.get_user_by_username(ctx, osu_username)
            osu_id = osu_user['id']
        if not osu_id:
            await ctx.send(f"I couldn't find the user \"{osu_username}\"")
            return
        member = members[0]
        cfg_member = self.config.member(member)
        await cfg_member.osu_id.set(osu_id)

        await ctx.send(f"Linked!")

    @osu.command(name='unregister')
    @commands.has_guild_permissions(administrator=True)
    async def user_unregistration_process(self, ctx: commands.Context, user_mention):
        """Tell me to stop tracking someone!
        """
        members = [m for m in ctx.message.mentions if not m.bot]
        if 0 == len(members) > 1:
            await ctx.send(f"Please only mention one user at a time!")
            return
        member = members[0]
        cfg_member = self.config.member(member)
        osu_id = await cfg_member.osu_id()
        if not osu_id:
            await ctx.send(f"They aren't registered currently!")
            return
        await cfg_member.osu_id.set(None)

        await ctx.send(f"Unregistered!")

    @osu.command(name='show')
    @commands.cooldown(1, 1)
    async def show_user_profile(self, ctx: commands.Context, *args):
        async with ctx.typing():
            if len(ctx.message.mentions) > 0:
                for member in ctx.message.mentions:
                    if member.bot:
                        continue
                    try:
                        cfg_member = self.config.member(member)
                        osu_id = await cfg_member.osu_id()
                        if osu_id is None:
                            await ctx.send(
                                f"{member.mention} does not appear to be registered!",
                                allowed_mentions=discord.AllowedMentions.none(),
                            )
                            continue
                        osu_user = await self.get_user_by_id(ctx, osu_id)
                        embed = await self.user_data_to_embed(osu_user)
                        await ctx.send(embed=embed)
                    except Exception as e:
                        raise e
            else:
                for username in args:
                    try:
                        osu_user = await self.get_user_by_username(ctx, username)
                        if osu_user is None:
                            await ctx.send(
                                f"{username} does not appear to be an existing osu! username",
                                allowed_mentions=discord.AllowedMentions.none(),
                            )
                            continue
                        embed = await self.user_data_to_embed(osu_user)
                        await ctx.send(embed=embed)
                    except Exception as e:
                        raise e

    @osu.command(name='updatenick')
    @commands.cooldown(1, 1)
    async def update_user_nicks(self, ctx: commands.Context, *args):
        if len(ctx.message.mentions) > 0:
            errors = []
            for member in ctx.message.mentions:
                if member.bot:
                    continue
                try:
                    cfg_member = self.config.member(member)
                    osu_id = await cfg_member.osu_id()
                    if osu_id is None:
                        await ctx.send(
                            f"{member.mention} is not yet registered! I don't know their osu! profile yet.",
                            allowed_mentions=discord.AllowedMentions.none(),
                        )
                        continue
                    oldnick = member.display_name
                    newnick = await self.update_user_nickname_with_rank(ctx, member)
                    await ctx.send(
                        f"Updated {member.mention}'s nickname, previously: {oldnick}",
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                except Exception as e:
                    await ctx.send(
                        f"I could not update the nickname of {member.mention}",
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                    errors.append(e)
                    continue
            if errors:
                raise errors[0]
        else:
            await ctx.send(f"Mention the users I should update!")
            return

    @osu.command(name='update_all_nicks', aliases=['pprain'])
    @commands.cooldown(1, 60, BucketType.guild)
    @commands.has_guild_permissions(administrator=True)
    async def update_all_user_nicks(self, ctx: commands.Context):
        print(f"Updating all nicks in {ctx.guild.name} at the request of {ctx.message.author.name} ({ctx.message.author.display_name})")
        async with ctx.typing():
            registered_update_count = 0
            unregistered_count = 0
            progressmsg = await ctx.send(f"Updating user nicknames...")
            errors = []
            start = get_timestamp_seconds()
            last_progress_edit = start
            member_cfgs = [] # (Member, Config, last_update)
            for member in ctx.guild.members:
                if member.bot:
                    continue
                cfg_member = self.config.member(member)
                member_cfgs.append( (member, cfg_member, await cfg_member.last_update()) )
            member_cfgs.sort(key=lambda t: t[2])
            for member, cfg_member, last_update in member_cfgs:
                print(f"manual update nick loop processing {member.display_name}")
                try:
                    osu_id = await cfg_member.osu_id()
                    if osu_id is None:
                        unregistered_count += 1
                    else:
                        await self.update_user_nickname_with_rank(ctx, member)
                        registered_update_count += 1
                except Exception as e:
                    await ctx.send(
                        f"Failed to update {member.mention}'s nickname: {type(e).__name__}",
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                    print(f"Exception: {type(e)}: {e}")
                    errors.append(e)
                # update status message
                if get_timestamp_seconds() > last_progress_edit:
                    await progressmsg.edit(
                        content=f"Updated {registered_update_count} nicks, skipped {unregistered_count} unregistered members so far..."
                    )
                    last_progress_edit = get_timestamp_seconds()
                await asyncio.sleep(1)
            await progressmsg.edit(
                content=f"Updated {registered_update_count} nicks, skipped {unregistered_count} unregistered members."
            )
            # if errors:
            #     raise errors[0]

    ### Task

    @tasks.loop(seconds=77.0)
    async def rank_update_loop(self):
        for guild in self.bot.guilds:
            cfg_guild = self.config.guild(guild)
            now = get_timestamp_seconds()

            # if now < last_post_time + autopostseconds:
            #     continue

            ctx = dotdict()
            ctx.cfg_guild = cfg_guild

            try:
                # iterate through users in this guild
                pass
            except LookupError as e:
                # this user might have rm'd their profile?
                print(f"WARN: {type(e)}: {e}")
                continue

    @rank_update_loop.before_loop
    async def wait_for_bot_ready(self):
        await self.bot.wait_until_ready()
