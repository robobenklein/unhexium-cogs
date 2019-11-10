import contextlib
import datetime
from datetime import timedelta, datetime as dt
from dateutil import tz
from fuzzywuzzy import fuzz, process
from fuzzywuzzy.utils import full_process as fuzzy_fullproc
import dateparser
import discord
from redbot.core import commands
from redbot.core import commands, Config

tz_UTC = tz.gettz('UTC')
tz_LOCAL = dt.now(datetime.timezone.utc).astimezone().tzinfo


async def allowed_to_edit(ctx: commands.Context, event: dict) -> bool:
    if not ctx.guild:
        return False
    if ctx.author.id == event["creator"]:
        return True
    elif await ctx.bot.is_mod(ctx.author):
        return True
    elif ctx.author == ctx.guild.owner:
        return True
    return False


def allowed_to_create():
    async def pred(ctx):
        if not ctx.guild:
            return False
        min_role_id = await ctx.cog.settings.guild(ctx.guild).min_role()
        if min_role_id == 0:
            min_role = ctx.guild.default_role
        else:
            min_role = discord.utils.get(ctx.guild.roles, id=min_role_id)
        if ctx.author == ctx.guild.owner:
            return True
        elif await ctx.bot.is_mod(ctx.author):
            return True
        elif ctx.author.top_role in sorted(ctx.guild.roles)[min_role.position :]:
            return True
        else:
            return False

    return commands.check(pred)


async def check_event_start(channel: discord.TextChannel, event: dict, config: Config):
    cur_time = dt.utcnow()
    guild = channel.guild
    if cur_time.timestamp() < event["event_start_time"] or event["has_started"]:
        return False, None
    event["has_started"] = True
    emb = get_event_embed(guild, cur_time, event)
    with contextlib.suppress(discord.Forbidden):
        if channel:
            await channel.send("Event starting now!", embed=emb)
    for user in [guild.get_member(m) for m in event["participants"] if guild.get_member(m)]:
        with contextlib.suppress(discord.Forbidden):
            if await config.member(user).dms():  # Only send to users who have opted into DMs
                await user.send("Event starting now!", embed=emb)

    return True, event


def get_event_embed(guild: discord.Guild, now: dt, event: dict) -> discord.Embed:
    emb = discord.Embed(title=event["event_name"], description=event["description"])
    emb.add_field(name="Created by", value="<@{}>".format(event["creator"]))
    emb.add_field(name="Event ID", value=str(event["id"]))
    emb.add_field(name="Participant count", value=str(len(event["participants"])))

    create_time = dt.fromtimestamp(event["create_time"], tz=tz_UTC)
    event_start_time = dt.fromtimestamp(event["event_start_time"], tz=tz_UTC)

    emb.timestamp = event_start_time
    created_str = create_time.strftime("%B %e %Y %R %Z")
    start_str = event_start_time.strftime("%B %e %Y %R %Z")

    emb.add_field(name="Created", value=created_str, inline=False)
    emb.add_field(name="Starts", value=start_str, inline=False)
    return emb


def get_delta_str(t1: dt, t2: dt) -> str:
    delta = t2 - t1
    hours, remainder = divmod(int(delta.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)
    days, hours = divmod(hours, 24)
    fmt = "{h}h {m}m {s}s"
    if days:
        fmt = "{d}d " + fmt
    return fmt.format(d=days, h=hours, m=minutes, s=seconds)


def does_event_match_search(event, search):
    if search is None:
        return True
    r = fuzz.partial_ratio(search, event["event_name"])
    if r > 90:
        return True
    try:
        i = int(search)
        if event["id"] == i:
            return True
    except:
        pass
    return False


def get_best_events_matching(event_list: list, search: str):
    if len(event_list) == 0:
        return []
    if search is None or len(search) == 0:
        return event_list
    try:
        i = int(search)
        for event in event_list:
            if event["id"] == event_id:
                return [event]
    except ValueError:
        pass
    except TypeError:
        pass
    # try doing a search through the names of events:
    event_names = [
        (e["event_name"], e) for e in event_list
    ]
    def process_by_first(v):
        return fuzzy_fullproc(v[0])
    results = process.extractBests(
        (search, None),
        event_names,
        processor=process_by_first,
        scorer=fuzz.partial_ratio,
        score_cutoff=90
    )
    rl = []
    for e, score in results:
        rl.append(e[1])
    return rl


async def parse_time(ctx: commands.Context, msg: discord.Message):
    """Parse the time"""
    d = dateparser.parse(msg.content)
    if d is None:
        return d

    if d.tzinfo is None or d.tzinfo.utcoffset(d) is None:
        # it's a naive datetime
        d.replace(tzinfo=tz_UTC)
        d = d.astimezone(tz_LOCAL)
        await ctx.send(
            "Assuming {} for the timezone! Specify the timezone if you want something else."
            .format(str(tz_LOCAL)),
            delete_after=60
        )
    return d
