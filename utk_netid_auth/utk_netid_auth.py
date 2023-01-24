
import asyncio
import concurrent.futures
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
import string
import os
import smtplib
import textwrap
from email.message import EmailMessage
from email.utils import formatdate

import discord
from async_timeout import timeout
from discord.ext import tasks
from discord.ext.commands import BucketType
# import requests
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

def get_timestamp_seconds():
    ts = time.time()
    return int(ts)

CODE_VALID_MINUTES = 20
vcard_link_fmt = "https://directory.utk.edu/vcard?p=vcard&dn=uid={netid},ou=People,ou=Knoxville,dc=tennessee,dc=edu&fn={netid}"


class UtkNetidAuth(commands.Cog):
    default_global = {
        # "known_users": [],
    }
    default_guild = {
        "auth_only_in_channel": None,
        "default_email_domain": None,
        "allowed_email_domains": [],
        "grant_role": None,
    }
    default_channel = {}
    default_user = {
        "authenticated": False,
        "authenticated_ts": None, # when they authenticated successfully
        "netid": None,
        "verifications": [], # codes sent for verification checks: {code, email, ts}
        # "valid_verifications": [], # TODO
    }
    default_member = {
        "authenticated": False,
        "valid_verification": None,
    }

    def __init__(self, bot: Red):
        self.bot = bot

        self.config = Config.get_conf(self, identifier=56988813)
        # self.session = aiohttp.ClientSession(
        #     loop=bot.loop,
        #     raise_for_status=True,
        #     timeout=aiohttp.ClientTimeout(total=30),
        # )
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=5)

        self.config.register_global(**self.default_global)
        self.config.register_guild(**self.default_guild)
        self.config.register_channel(**self.default_channel)
        self.config.register_user(**self.default_user)
        self.config.register_member(**self.default_member)

    async def cog_before_invoke(self, ctx: commands.Context):
        ctx.cfg_guild = self.config.guild(ctx.guild)
        ctx.cfg_channel = self.config.channel(ctx.channel)
        ctx.cfg_user = self.config.user(ctx.author)
        ctx.cfg_member = self.config.member(ctx.author)

    async def send_verification_email(self, ctx: commands.Context, email):
        async with ctx.cfg_user.verifications() as verifications:
            for i, v in list(enumerate(verifications)):
                if v['ts'] < get_timestamp_seconds() - (CODE_VALID_MINUTES*60):
                    verifications.remove(v)

            code = ''.join(random.choice(string.digits) for _ in range(4))

            while code in [v['code'] for v in verifications]:
                code = ''.join(random.choice(string.digits) for _ in range(4))

            print(f"Send email to {email} with code {code}")

            em = EmailMessage()
            em.set_content(textwrap.dedent(f"""\
            Your verification code is {code}.
            It is valid for {CODE_VALID_MINUTES} minutes from when you sent your message.

            Command to copy-paste:
            utk auth verify {code}

            This code was requested by Discord user {str(ctx.author)} in the server {str(ctx.guild)}.

            If this was *not* requested by you, please let the admins or moderators of the server know.
            """))
            em['Subject'] = f"Your Discord verification code for {ctx.guild}"
            em['From'] = os.environ.get('SMTP_FROM_ADDRESS')
            em['To'] = email
            em['Date'] = formatdate()

            def send_da_mail():
                s = smtplib.SMTP_SSL(
                    host=os.environ.get('SMTP_HOST'),
                )
                print(f"SMTP connected, logging in ...")
                s.login(os.environ.get('SMTP_USER'), os.environ.get('SMTP_PASSWORD'))
                print(f"SMTP logged in, sending ...")
                s.send_message(em)
                print(f"SMTP done, disconnecting ...")
                s.quit()

            waiting_msg = await ctx.reply(f"Delivering email... please wait... (should not take more than 5 minutes)")
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(self.executor, send_da_mail)
            await waiting_msg.delete()

            verifications.append({
                'code': code,
                'email': email,
                'ts': get_timestamp_seconds(),
            })

    ### NOTE Commands

    @commands.group(name='auth', aliases=[])
    async def auth(self, ctx: commands.Context):
        """Authenticate yourself!"""
        pass

    @auth.group(name='admin')
    @commands.admin()
    async def admin(self, ctx: commands.Context):
        """Admin commands for configuring authentication."""
        pass
        # default_domain = await ctx.cfg_guild.default_email_domain()
        # await ctx.reply((
        #     f"Current configuration:\n"
        #     f"Default email domain: {default_domain}"
        # ))

    @admin.command(name='default_domain', aliases=['domain'])
    async def admin_set_default_email_domain(self, ctx: commands.Context, domain: str):
        """Set the default email domain for the guild."""
        await ctx.cfg_guild.default_email_domain.set(domain)
        await ctx.reply(f"Default email domain set to {domain}")

    @admin.command(name='role')
    async def admin_set_role(self, ctx: commands.Context, role_id: int = None):
        """Set the role to grant users when they successfully authenticate."""
        old_role_id = await ctx.cfg_guild.grant_role()
        if role_id:
            async with ctx.typing():
                role = ctx.guild.get_role(role_id)
                if not role:
                    return await ctx.reply(f"Role with that ID not found!")
                await ctx.cfg_guild.grant_role.set(role.id)
                await ctx.reply(
                    f"Will grant {role.mention} on successful verification.",
                    allowed_mentions = discord.AllowedMentions(roles=False),
                )
        else:
            if old_role_id:
                role = ctx.guild.get_role(old_role_id)
                await ctx.reply(
                    f"Currently granting role {role.mention}",
                    allowed_mentions = discord.AllowedMentions(roles=False),
                )
            else:
                await ctx.reply(f"Not currently granting any role on auth.")

    @auth.command(name='netid')
    async def auth_with_netid(self, ctx: commands.Context, netid: str):
        """Authenticate using a netid"""
        async with ctx.typing():
            domain = await ctx.cfg_guild.default_email_domain()
            if not domain:
                await ctx.reply(f"Error processing request, please let the admins know! Error:`NODEFAULTDOMAIN`")
                return
            email = f"{netid}@{domain}"

            await self.send_verification_email(ctx, email)

            await ctx.reply(f"Verification mail sent to {email}! (please remember to check spam as well!)")

    @auth.command(name='verify')
    async def auth_verify(self, ctx: commands.Context, code: str):
        """Verify a code that was sent to you."""
        async with ctx.typing():
            # clear out expired:
            async with ctx.cfg_user.verifications() as verifications:
                for i, v in list(enumerate(verifications)):
                    if v['ts'] < get_timestamp_seconds() - (CODE_VALID_MINUTES*60):
                        verifications.remove(v)

            verifications = await ctx.cfg_user.verifications()

            if code not in [v['code'] for v in verifications]:
                await ctx.reply(f"That code doesn't appear to be valid!")
                return

            verification = [v for v in verifications if v['code'] == code][-1]
            assert verification

            await ctx.cfg_member.valid_verification.set(verification)
            grant_role_id = await ctx.cfg_guild.grant_role()
            if grant_role_id:
                role = ctx.guild.get_role(grant_role_id)
                await ctx.author.add_roles(
                    role,
                    reason="Role granted by successful verification",
                )

            return await ctx.reply(f"Verification successful!")
