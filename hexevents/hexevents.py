import asyncio
import contextlib
import datetime
from datetime import datetime as dt, timedelta
from dateutil import tz

from fuzzywuzzy import process, fuzz

import discord
from redbot.core import commands
from redbot.core import Config, commands, checks
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import pagify, warning
from redbot.core.i18n import Translator

from .helpers import (
    parse_time,
    allowed_to_create,
    get_event_embed,
    allowed_to_edit,
    check_event_start,
    does_event_match_search,
    get_best_events_matching,
)
from .menus import event_menu

_ = Translator("HexEvents", __file__)


class HexEvents(commands.Cog):
    """
    A tool for creating events inside of Discord. Anyone can
    create an event by default. If a specific role has been
    specified, users must have that role or any role above it in
    the hierarchy or be the server owner to create events.
    """

    default_guild = {"events": [], "min_role": 0, "next_available_id": 1, "channel": 0}

    default_member = {"dms": False}

    def __init__(self, bot: Red):
        self.bot = bot
        self.settings = Config.get_conf(self, identifier=3726891735, force_registration=True)
        self.settings.register_guild(**self.default_guild)
        self.settings.register_member(**self.default_member)
        loop = self.bot.loop
        self.event_check_task = loop.create_task(self.check_events())

    def cog_unload(self):
        self.event_check_task.cancel()

    @commands.group(aliases=["events"])
    @commands.guild_only()
    async def event(self, ctx: commands.Context):
        """Base command for events"""
        pass

    @event.command(name="create", aliases=["new"])
    @allowed_to_create()
    async def event_create(self, ctx: commands.Context, *, event_name: str = None):
        """
        Wizard-style event creation tool.
        The event will only be created if all information is provided properly.
        If a minimum required role has been set, users must have that role or
        higher, be in the mod/admin role, or be the guild owner in order to use this command
        """
        author = ctx.author
        guild = ctx.guild

        event_id = await self.settings.guild(guild).next_available_id()

        await ctx.send(_("You can edit these fields later, don't worry about making mistakes right now!"))
        await ctx.send(_("Say \"cancel\" at any point to stop without creating the event!"))

        def same_author_check(msg):
            return msg.author == author
        creation_time = ctx.message.created_at

        # WHAT
        if event_name is None:
            await ctx.send(_("Enter a name for the event: "))
            msg = await self.bot.wait_for("message", check=same_author_check)
            name = msg.content
            if "cancel" == name.lower():
                await ctx.send(_("Canceled!"), delete_after=10)
                return
        else:
            name = event_name
        if len(name) > 256:
            await ctx.send(_(
                "That name is too long! Event names "
                "must be 256 charcters or less."
            ))
            return

        # WHEN
        await ctx.send(_(
            "When will this event take place? "
            "Please specify a single point in time, like \"next week, 2pm on thursday\""
        ))
        start_time = None
        while start_time is None:
            msg = await self.bot.wait_for("message", check=same_author_check)
            if "cancel" in msg.content.lower() or "stop" in msg.content.lower():
                await ctx.send(_("Canceled!"), delete_after=10)
                return

            start_time = await parse_time(ctx, msg)
            if start_time is None:
                await ctx.send(_("Something went wrong with parsing the time you entered!"), delete_after=60)
                await ctx.send(_("Please try a specific single point in time. 'cancel' to stop."), delete_after=60)
            else:
                await ctx.send("Understood that as " + start_time.strftime('%F %R / %l%P %Z'))
                await ctx.send("You can edit that later if it's wrong.", delete_after=30)

        # DETAILS
        await ctx.send(_("Enter a description for the event: (max 1k characters)"))
        msg = await self.bot.wait_for("message", check=same_author_check)
        desc = msg.content
        if len(desc) > 1000:
            await ctx.send(_("Truncating to 1k chars..."))
            desc = desc[:1000]

        new_event = {
            "id": event_id,
            "creator": author.id,
            "create_time": int(creation_time.timestamp()),
            "event_name": name,
            "event_start_time": int(start_time.timestamp()),
            "description": desc,
            "has_started": False,
            "participants": [author.id],
        }
        async with self.settings.guild(guild).events() as event_list:
            event_list.append(new_event)
            event_list.sort(key=lambda x: x["create_time"])
        await ctx.send(embed=get_event_embed(guild, ctx.message.created_at, new_event))

    @event.command(name="join")
    async def event_join(self, ctx: commands.Context, *, search: str):
        """Join an event"""
        guild = ctx.guild
        to_join = None
        async with self.settings.guild(guild).events() as event_list:
            for event in event_list:
                if event["id"] == event_id:
                    to_join = event
                    event_list.remove(event)
                    break

            if not to_join["has_started"]:
                if ctx.author.id not in to_join["participants"]:
                    to_join["participants"].append(ctx.author.id)
                    await ctx.tick()
                    event_list.append(to_join)
                    event_list.sort(key=lambda x: x["id"])
                else:
                    await ctx.send("You have already joined that event!")
            else:
                await ctx.send("That event has already started!")

    @event.command(name="force_add", aliases=["add"])
    @checks.admin_or_permissions(manage_guild=True)
    async def event_force_add_user(self, ctx: commands.Context, *, event_search: str):
        guild = ctx.guild
        author = ctx.author
        async with self.settings.guild(guild).events() as event_list:
            matches = get_best_events_matching(event_list, event_search)
            if len(matches) == 0:
                await ctx.send(_("I could not find an event matching that search!"))
                return
            elif len(matches) > 1:
                await ctx.send(_("Please be more specific! Which are you referring to?"))
                await event_menu(ctx, [m[0] for m in matches], message=None, page=0, timeout=30)
                return
            target_event = matches[0]

            def same_author_check(msg):
                return msg.author == author

            await ctx.send(
                _("Please mention everyone you want to add to \"")
                + target_event["event_name"] + "\""
            )
            try:
                msg = await self.bot.wait_for("message", check=same_author_check, timeout=600)
            except asyncio.TimeoutError:
                ctx.send("Timeout waiting for new users.", remove_after=30)
                return
            new_peeps = msg.raw_mentions
            for peep_id in new_peeps:
                if peep_id not in target_event["participants"]:
                    target_event["participants"].append(peep_id)
                else:
                    new_peeps.remove(peep_id)
            await ctx.send(
                ("Added {} new attendee" + ("s." if len(new_peeps) != 1 else "."))
                .format(len(new_peeps))
                + " Event now has {} total attendees."
                .format(len(target_event["participants"]))
            )


    @event.command(name="leave")
    async def event_leave(self, ctx: commands.Context, *, event_search: str):
        """Leave the specified event"""
        guild = ctx.guild
        to_leave = None
        async with self.settings.guild(guild).events() as event_list:
            for event in event_list:
                if event["id"] == event_id:
                    to_leave = event
                    event_list.remove(event)
                    break

            if not to_leave["has_started"]:
                if ctx.author.id in to_leave["participants"]:
                    to_leave["participants"].remove(ctx.author.id)
                    await ctx.send("Left the event!")
                    event_list.append(to_leave)
                    event_list.sort(key=lambda x: x["id"])
                else:
                    await ctx.send("You are not part of that event!")

    @event.command(name="list", aliases=["ls", "show"])
    async def event_list(self, ctx: commands.Context, *, event_search: str = None):
        """List events for this server"""
        guild = ctx.guild
        event_embeds = []
        async with self.settings.guild(guild).events() as event_list:
            for event in get_best_events_matching(event_list, event_search):
                emb = get_event_embed(guild, ctx.message.created_at, event)
                event_embeds.append(emb)
        if len(event_embeds) == 0:
            await ctx.send(
                _("No events by that search!")
                if event_search else
                _("No events available!")
            )
        else:
            await ctx.send(str(len(event_embeds)) + _(" events to show:"))
            await event_menu(ctx, event_embeds, message=None, page=0, timeout=30)

    @event.command(name="who")
    async def event_who(self, ctx: commands.Context, *, event_search: str):
        """List all participants for the event"""
        guild = ctx.guild
        async with self.settings.guild(guild).events() as event_list:
            matches = get_best_events_matching(event_list, event_search)
            if len(matches) == 0:
                await ctx.send(_("I could not find an event matching that search!"))
                return
            elif len(matches) > 1:
                await ctx.send(_("Please be more specific! Which are you referring to?"))
                await event_menu(ctx, [m[0] for m in matches], message=None, page=0, timeout=30)
                return
            target_event = matches[0]

            mbr_list = [
                "<@{}>".format(uid)
                for uid in target_event["participants"]
                # if guild.get_member(uid)
            ]
            participants = "\n".join(mbr_list)
            for pg in pagify(participants):
                emb = discord.Embed(title="Event Participants")
                emb.description = participants
                emb.set_footer(text=target_event["event_name"])
                emb.timestamp = dt.fromtimestamp(target_event["event_start_time"])
                await ctx.send(embed=emb)

    @event.command(name="edit", aliases=["change", "modify"])
    async def event_edit(self, ctx: commands.Context, *, selection: str):
        """Edit details about an event."""
        try:
            event_search, attribute = selection.rsplit(maxsplit=1)
        except ValueError:
            await ctx.send(_("Please specify both the event name and then the attribute you want to edit!"))
            return
        author = ctx.author
        guild = ctx.guild
        async with self.settings.guild(guild).events() as event_list:
            matches = get_best_events_matching(event_list, event_search)
            if len(matches) == 0:
                await ctx.send(_("I could not find an event matching that search!: ") + event_search)
                return
            elif len(matches) > 1:
                await ctx.send(_("Please be more specific! Which are you referring to?"))
                await event_menu(ctx, [m[0] for m in matches], message=None, page=0, timeout=30)
                return
            target_event = matches[0]
            if not await allowed_to_edit(ctx, target_event):
                await ctx.send(_("You are not allowed to edit that event!"))
                return

            target_event = matches[0]
            if attribute.lower() in ["name", "title"]:
                attribute = "event_name"
            elif attribute.lower() in ["desc", "description", "details", "about"]:
                attribute = "description"
            elif attribute.lower() in ["time", "when", "start"]:
                attribute = "event_start_time"

            if attribute not in target_event:
                await ctx.send(_("Not sure what about the event you want to edit!"))
                await ctx.send(_("Try one of: name, desc, time"), delete_after=30)
                return

    @event.command(name="cancel", aliases=["rm", "delete", "remove"])
    async def event_cancel(self, ctx: commands.Context, *, event_search: str):
        """Cancels the specified event"""
        guild = ctx.guild
        async with self.settings.guild(guild).events() as event_list:
            matches = get_best_events_matching(event_list, event_search)
            if len(matches) == 0:
                await ctx.send(_("I could not find an event matching that search!: ") + event_search)
                return
            elif len(matches) > 1:
                await ctx.send(_("Please be more specific! Which are you referring to?"))
                await event_menu(ctx, [m[0] for m in matches], message=None, page=0, timeout=30)
                return
            to_remove = matches[0]
            if not await allowed_to_edit(ctx, to_remove):
                await ctx.send(_("You are not allowed to edit that event!"))
                return

            msg = await ctx.send(
                "Confirm deleting event '{}' (id {}) by reacting to this message!"
                .format(to_remove["event_name"], to_remove["id"])
            )
            def check(reaction, user):
                return user == ctx.message.author and reaction.message.id == msg.id

            try:
                reaction, user = await ctx.bot.wait_for('reaction_add', check=check, timeout=60.0)
            except asyncio.TimeoutError:
                await ctx.send(_("Timeout: not deleting event."))
                return
            else:
                event_list.remove(to_remove)
                await ctx.send(_("Event deleted!"))
                await msg.delete()


    @commands.group()
    @commands.guild_only()
    async def eventset(self, ctx: commands.Context):
        """Event maker settings"""
        pass

    @eventset.command(name="toggledms")
    @commands.guild_only()
    async def eventset_toggledms(self, ctx: commands.Context, user: discord.Member = None):
        """
        Toggles event start announcement DMs for the specified user
        By default, users will not receive event start announcements via DM
        If `user` is not specified, toggle for the author.
        Only admins and the guild owner may toggle DMs for users other than themselves
        """
        if user:
            if not await ctx.bot.is_admin(ctx.author) and not ctx.author == ctx.guild.owner:
                await ctx.send("You are not allowed to toggle that for other users!")
                return
        if not user:
            user = ctx.author
        cur_val = await self.settings.member(user).dms()
        await self.settings.member(user).dms.set(False if cur_val else True)
        await ctx.tick()

    @eventset.command(name="role")
    @checks.admin_or_permissions(manage_guild=True)
    async def eventset_role(self, ctx: commands.Context, *, role: discord.Role = None):
        """Set the minimum role required to create events.
        Default is for everyone to be able to create events"""
        guild = ctx.guild
        if role is not None:
            await self.settings.guild(guild).min_role.set(role.id)
            await ctx.send("Role set to {}".format(role))
        else:
            await self.settings.guild(guild).min_role.set(0)
            await ctx.send("Role unset!")

    @eventset.command(name="resetevents")
    @checks.guildowner_or_permissions(administrator=True)
    async def eventset_resetevents(self, ctx: commands.Context, confirm: str = None):
        """
        Resets the events list for this guild
        """
        if confirm is None or confirm.lower() != "yes":
            await ctx.send(
                warning(
                    "This will remove all events for this guild! "
                    "This cannot be undone! To confirm, type "
                    "`{}eventset resetevents yes`".format(ctx.prefix)
                )
            )
        else:
            await self.settings.guild(ctx.guild).events.set([])
            await self.settings.guild(ctx.guild).next_available_id.set(1)
            await ctx.tick()

    @eventset.command(name="channel")
    @checks.admin_or_permissions(manage_guild=True)
    async def eventset_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """
        Sets the channel where event start announcements will be sent
        If this is not set, the channel will default to the channel used
        for new member messages (Server Settings > Overview > New Member
        Messages Channel on desktop). If that is set to `No new member messages`,
        the event start announcement will not be sent to a channel in the server
        and will only be sent directly to the participants via DM
        """
        await self.settings.guild(ctx.guild).channel.set(channel.id)
        await ctx.tick()

    async def check_events(self):
        CHECK_DELAY = 300
        while self == self.bot.get_cog("EventMaker"):
            for guild in self.bot.guilds:
                async with self.settings.guild(guild).events() as event_list:
                    channel = guild.get_channel(await self.settings.guild(guild).channel())
                    if channel is None:
                        channel = guild.system_channel
                    for event in event_list:
                        changed, data = await check_event_start(channel, event, self.settings)
                        if not changed:
                            continue
                        event_list.remove(event)
                        event_list.append(data)
                    event_list.sort(key=lambda x: x["create_time"])
            await asyncio.sleep(CHECK_DELAY)
