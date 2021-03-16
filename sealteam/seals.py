
import asyncio
import functools
import itertools
import math
import random
import re

import discord
from async_timeout import timeout
# from discord.ext import commands

from redbot.core import commands
from redbot.core import Config, commands, checks
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import pagify, warning
from redbot.core.i18n import Translator

e_qs = {}


attack_begin_callouts = [
    "{other_seal} I'll cover you!",
    "Right behind you {other_seal}!",
    "{other_seal} and I are moving in!",
    "Bringing up the rear!",
    "{other_seal} did you forget your helmet?",
    "Hurry up {other_seal}!",
    "Almost ready!",
    "{other_seal} have you seen my croutonium rounds magazine?",
    "I call shotgun!",
    "Was it really a good idea to give {other_seal} the RPG this time?",
    "{mentioner} {other_seal} looks a bit tipsy, you sure about this?",
    "I've been flippin waiting for this {mentioner}!",
    "You coming {mentioner}?",
    "{other_seal} don't make the same mistake you did last time.",
    "{other_seal} pick up the pace!",
    "Where's my rifle?",
    "{mentioner} bad news, {other_seal} is drunk.",
    "Maybe this isn't a good idea?",
    "How am I supposed to fight *that*?",
    "Stop pushing {other_seal}!",
    "It's my turn next {other_seal}.",
    "... you woke me up for this?",
    "I need better weapons than this!",
    "Who are we fighting?",
    "{other_seal} watch your step!",
    "I'd feel better if {other_seal} didn't steal my rations.",
    "I hope we're getting overtime pay for this {mentioner}",
    "You do know we don't have fingers, right {mentioner}?",
    "Who's got the radio?",
    "*unintelligible seal noises*",
    "I've got the bucket!",
    "I need more weapons!",
    "Where's the bucket?",
]

class SealTeamMember(commands.Cog):
    def __init__(self, bot: Red):
        self.bot = bot

    # def cog_unload(self):
    #     for state in self.voice_states.values():
    #         self.bot.loop.create_task(state.stop())
    #
    #     return state

    def cog_check(self, ctx: commands.Context):
        if not ctx.guild:
            raise commands.NoPrivateMessage('This command can\'t be used in DM channels.')

        return True

    # async def cog_before_invoke(self, ctx: commands.Context):
    #     ctx.voice_state = self.get_voice_state(ctx)

    # async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
    #     if isinstance(error, commands.MissingPermissions):
    #         await ctx.send('Music: do you have permission to do that?')
    #     else:
    #         await ctx.send('Music: An error occurred: {}'.format(str(error)))

    ### NOTE Commands

    @commands.Cog.listener('on_message')
    async def on_message(self, message):
        if ':elephantseal' not in message.content:
            return
        if 'attack' not in message.content.lower():
            return

        guild = message.guild

        other_bots = [
            m for m in guild.members if m.bot and m.status == discord.Status.online and m != self.bot.user
        ]

        vars = {
            "other_seal": random.choice(other_bots).mention,
            "mentioner": message.author.mention,
        }

        await message.channel.send(
            random.choice(attack_begin_callouts).format(**vars)
        )
