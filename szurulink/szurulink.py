
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
import typing
from enum import Enum
from operator import itemgetter

import discord
import discord.ui
from async_timeout import timeout
from discord.ext import tasks
import discord.ext.commands
import requests
import aiohttp

from redbot.core import commands, app_commands
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

class SzuruLinkUserNotLoggedIn(RuntimeError):
    pass

class SzuruSafetyRating(Enum):
    safe = 'safe'
    sketchy = 'sketchy'
    unsafe = 'unsafe'

SzuruSafetyRatingEmoji = {
    'safe': '🟩', # green
    'sketchy': '🟨', # yellow
    'unsafe': '🟥', # red
}


class SzuruPostUploadSafetyPrompt(discord.ui.View):
    @discord.ui.select(options=[
        discord.SelectOption(
            label=r.value, emoji=SzuruSafetyRatingEmoji[r.value],
        ) for r in SzuruSafetyRating
    ])
    async def on_safety_selected(
            self, interaction: discord.Interaction,
            selected,
        ):
        print(f"on_safety_selected: {type(selected)} {selected}")
        # await interaction.response.send_message(f"Selected safety {selected.values}")
        self.stop()
        return selected.values[0]


class SzuruPoster(commands.Cog):

    default_global = {
        "autoposttimer": 10,
        "max_searchresults": 3,
    }
    default_guild = {
        "autopostchannel": None,
        "autopostseconds": 3600,
        "autopost_exclude_unsafe": False,
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
        "szuruname": None,
        "szurutoken": None,
    }

    def __init__(self, bot: Red):
        self.bot = bot

        self.config = Config.get_conf(self, identifier=435619873)
        self.session = aiohttp.ClientSession(
            loop=bot.loop,
            raise_for_status=False
        )

        self.config.register_global(**self.default_global)
        self.config.register_guild(**self.default_guild)
        self.config.register_channel(**self.default_channel)
        self.config.register_member(**self.default_member)

        self._serverinfo_cache = dict()

        self.check_send_next_post.start()

        self.ctx_menu = app_commands.ContextMenu(
            name='Update Post Embed',
            callback=self.update_post_embed_by_context_menu,
        )
        self.bot.tree.add_command(self.ctx_menu)

    def cog_unload(self):
        self.bot.tree.remove_command(self.ctx_menu.name, type=self.ctx_menu.type)
        self.check_send_next_post.cancel()
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

    async def update_interaction_context(self, interaction: discord.Interaction, ctx: commands.Context):
        """This function is different than cog_before_invoke because an interaction user may be different than the generated context object."""
        ctx.cfg_guild = self.config.guild(ctx.guild)
        ctx.cfg_channel = self.config.channel(ctx.channel)
        ctx.cfg_member = self.config.member(interaction.user)

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        print(f"sz: handling error {type(error)}: {error}")
        if isinstance(error, commands.MissingPermissions):
            await ctx.send('SzuruLink: do you have permission to do that?')
        elif isinstance(error, aiohttp.client_exceptions.ClientResponseError):
            await ctx.send(f'SzuruLink: server error: {error}')
            print(f"error {error}")
            print(f"request: {error.request_info}")
            # print(f"")
            raise error
        elif isinstance(error, discord.ext.commands.CommandInvokeError) and isinstance(error.original, SzuruLinkUserNotLoggedIn):
            await ctx.send(f'SzuruLink: You aren\'t logged in!' + (f" {error.original}" if error.original.args else ""))
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
            await self.get_url_file_buffer(data['_']['media_url']),
            filename=data['_']['filename'],
            spoiler=data['_']['unsafe'],
        )
        return attach

    async def get_api_url(self, ctx: commands.Context):
        cu = await ctx.cfg_channel.api_url()
        return f"{cu}/api"

    async def get_server_info(self, ctx: commands.Context):
        au = await self.get_api_url(ctx)
        # no auth for server info path
        r = await self.session.get(
            f"{au}/info",
            headers={
                'Accept': 'application/json',
            }
        )
        try:
            info = await r.json()
        except json.decoder.JSONDecodeError as e:
            # what to do here?
            raise e

        self._serverinfo_cache[au] = info
        return info

    # async def does_server_use_safety(self, ctx: commands.Context):
    #

    async def api_get(self, ctx: commands.Context, path):
        au = await self.get_api_url(ctx)
        if not au:
            raise ValueError("There's no API URL set for this channel!")
        api_user = await ctx.cfg_channel.api_user()
        api_token = await ctx.cfg_channel.api_token()
        auth = stringToBase64(f"{api_user}:{api_token}")

        r = await self.session.get(
            f"{au}{path}",
            headers={
                'Authorization': f"Token {auth}",
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            }
        )
        try:
            return await r.json()
        except json.decoder.JSONDecodeError as e:
            print(f"error: {r}: {e}")
            print(r.text)
            raise RuntimeError("Failed to parse response from server.")

    async def user_api_get(self, ctx, path):
        au = await self.get_api_url(ctx)
        api_user = await ctx.cfg_member.szuruname()
        api_token = await ctx.cfg_member.szurutoken()
        auth = stringToBase64(f"{api_user}:{api_token}")

        r = await self.session.get(
            f"{au}{path}",
            headers={
                'Authorization': f"Token {auth}",
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            }
        )
        try:
            return await r.json()
        except json.decoder.JSONDecodeError as e:
            print(f"error: {r}: {e}")
            print(r.text)
            raise RuntimeError("Failed to parse response from server.")

    async def user_api_upload_tempfile(self, ctx, filecontent):
        au = await self.get_api_url(ctx)
        api_user = await ctx.cfg_member.szuruname()
        api_token = await ctx.cfg_member.szurutoken()
        if not api_user or not api_token:
            raise SzuruLinkUserNotLoggedIn()
        auth = stringToBase64(f"{api_user}:{api_token}")

        # TODO switch back to async request
        # # print(f"filecontent type: {type(filecontent)} size {len(filecontent)}")
        # with aiohttp.MultipartWriter('mixed') as mpwriter:
        #     part = mpwriter.append(
        #         BytesIO(filecontent),
        #         # {"Content-Type": "multipart/form-data"}
        #     )
        #     part.set_content_disposition('form-data', name="content")
        #     # with aiohttp.MultipartWriter('related') as subwriter:
        #     #     mpwriter.append_json(json_data)
        #     # mpwriter.append(subwriter)
        #     # with aiohttp.MultipartWriter('related') as subwriter:
        #     # mpwriter.append(subwriter)
        # # print(f"made mpwriter {mpwriter}")
        # r = await self.session.post(
        #     f"{au}/uploads",
        #     headers={
        #         'Authorization': f"Token {auth}",
        #         # 'Content-Type': 'multipart/form-data',
        #         'Accept': 'application/json',
        #     },
        #     data=mpwriter,
        #     raise_for_status=False,
        # )
        #
        # return await r.json()

        r = requests.post(
            f"{au}/uploads",
            headers={
                'Authorization': f"Token {auth}",
                # 'Content-Type': 'multipart/form-data',
                'Accept': 'application/json',
            },
            files={'content': BytesIO(filecontent)}
        )
        return r.json()

    # async def user_api_upload_post(self, ctx, json_data, filecontent):
    #     au = await self.get_api_url(ctx)
    #     api_user = await ctx.cfg_member.szuruname()
    #     api_token = await ctx.cfg_member.szurutoken()
    #     auth = stringToBase64(f"{api_user}:{api_token}")
    #
    #     # TODO async
    #     req = requests.Request(
    #         'POST',
    #         f"{au}/posts/",
    #         data=json_data,
    #         files={
    #             # "json": (None, json.dumps(json_data), 'application/json'),
    #             "content": ('discord-upload', BytesIO(filecontent), 'image/unknown'),
    #         },
    #         headers={
    #             'Authorization': f"Token {auth}",
    #             'Accept': 'application/json',
    #         },
    #     )
    #     prepped = req.prepare()
    #     print(prepped.body.decode('ascii', errors='ignore'))
    #     headers = '\n'.join(['{}: {}'.format(*hv) for hv in prepped.headers.items()])
    #     print(headers)
    #
    #     with requests.Session() as s:
    #         r = s.send(prepped)
    #         print(r)
    #         r.raise_for_status()
    #         return r.json()

    async def user_api_post(self, ctx, path, *, json_data = {}):
        au = await self.get_api_url(ctx)
        api_user = await ctx.cfg_member.szuruname()
        api_token = await ctx.cfg_member.szurutoken()
        if not api_user or not api_token:
            raise SzuruLinkUserNotLoggedIn()
        auth = stringToBase64(f"{api_user}:{api_token}")

        r = await self.session.post(
            f"{au}{path}",
            headers={
                'Authorization': f"Token {auth}",
                # 'Content-Type': 'application/json',
                'Accept': 'application/json',
            },
            json=json_data,
            raise_for_status=True,
        )
        try:
            print(f"resp {r} {r.status}:")
            print(f"req {r.request_info}")
            print(await r.text())
            return await r.json()
        except json.decoder.JSONDecodeError as e:
            print(f"error: {r}: {e}")
            print(r.text)
            raise RuntimeError("Failed to parse response from server.")

    async def user_api_login_bump(self, ctx):
        user = await ctx.cfg_member.szuruname()
        return await self.user_api_get(ctx, f"/user/{user}?bump-login")

    async def _augment_post_data(self, ctx, data: dict):
        cu = await ctx.cfg_channel.api_url()
        unsafe = True if data['safety'] == "unsafe" else False
        embed_visible = False if data['type'] == 'video' else True
        data['_'] = {
            "media_url": f"{cu}/{data['contentUrl']}" if "://" not in data['contentUrl'] else data['contentUrl'],
            "post_url": f"{cu}/post/{data['id']}",
            "embed_visible": embed_visible,
            "unsafe": unsafe,
            "filename": data['contentUrl'].split('/')[-1],
            "user": None,
            "should_embed": not unsafe and embed_visible,
            # "message_content": f"{cu}/{data['contentUrl']}",
        }
        if unsafe:
            data['_']["message_content"] = f"Post {data['id']}: {spoiler(data['_']['media_url'])}"
        elif not embed_visible:
            # TODO discord still won't render a preview :/
            # maybe check size and upload if under limit?
            data['_']["message_content"] = f"Post {data['id']}: {data['_']['media_url']}"
        else:
            data['_']["message_content"] = f"Post {data['id']}:"
        if 'user' in data and data['user']:
            data['_']["user"] = {
                "icon_url": f"{cu}/{data['user']['avatarUrl']}" if "://" not in data['user']['avatarUrl'] else data['user']['avatarUrl'],
                "name": data['user']['name'],
                "url": f"{cu}/user/{data['user']['name']}",
            }
        return data

    async def get_post_by_id(self, ctx: commands.Context, postid):
        # cu = await ctx.cfg_channel.api_url()
        data = await self.api_get(ctx, f"/post/{postid}")
        if 'name' in data and data['name'] == 'PostNotFoundError':
            raise LookupError(f"No such post with ID {postid}")

        return await self._augment_post_data(ctx, data)

    async def get_posts_by_query(self, ctx, user_query: str):
        cu = await ctx.cfg_channel.api_url()
        max = await self.config.max_searchresults()
        urlquery = urllib.parse.urlencode({
            "query": user_query,
            "limit": max,
            "fields": "id,thumbnailUrl,contentUrl,type,safety,score,favoriteCount,commentCount,tags,user,version",
            # "offset": 0,
        })
        data = await self.api_get(ctx, f"/posts/?{urlquery}")
        # await ctx.send(box(str(data)[:499]))

        # print(data)

        data['_'] = {
            'results': [await self._augment_post_data(ctx, x) for x in data['results']],
        }
        return data

    async def post_data_to_embed(self, data, *, include_image=True):
        embed = discord.Embed(
            title=f"Post {data['id']}",
            url=data['_']['post_url'],
            # description="TODO",
        )
        if data['_']['user']:
            embed.set_author(**data['_']['user'])
        if include_image:
            embed.set_image(url=data['_']['media_url'])
        # 'tags': [{'names': ['animal_ears'], 'category': 'default', 'usages': 260}, {'names': ['cat_tail'], 'category': 'default', 'usages': 62},
        if data['tags']:
            tag_string = escape(', '.join([
                f"{x['names'][0]} ({x['usages']})"
                for x in data['tags']
            ]), formatting=True)
            if len(tag_string) > 1000:
                # discord limitation 1024 chars, choose which tags to show
                default_tags = [tag for tag in data['tags'] if tag['category'] == 'default']
                other_tags = [tag for tag in data['tags'] if tag['category'] != 'default']
                default_tags.sort(key=lambda t: t['usages'])
                other_tags.sort(key=lambda t: t['usages'])

                tag_string = ""
                next_tag_string = ""
                while len(escape(next_tag_string, formatting=True)) < 950:
                    tag_string = next_tag_string
                    if other_tags:
                        next_tag = other_tags.pop()
                    elif default_tags:
                        next_tag = default_tags.pop()
                    else:
                        break
                    next_tag_string += f"{next_tag['names'][0]} ({next_tag['usages']}), "
                print(f"szurulink: snipped large tag list to {len(tag_string)} chars,")
                remaining_tag_count = len(default_tags) + len(other_tags)
                tag_string += f"\n{remaining_tag_count} more tag(s) not shown"
                tag_string = escape(tag_string, formatting=True)
                print(f"szurulink: total embed field length: {len(tag_string)}")

            embed.add_field(
                name="Tags",
                value=tag_string,
                inline=False,
            )
        if data['score']:
            embed.add_field(
                name="Votes",
                value=data['score'],
                inline=True,
            )
        if data['favoriteCount']:
            embed.add_field(
                name="Favorites",
                value=data['favoriteCount'],
                inline=True,
            )
        if data['type'] != "image":
            embed.add_field(
                name="Type",
                value=data['type'],
                inline=True,
            )
        if 'relations' in data and data['relations']:
            embed.add_field(
                name="Related",
                value=', '.join([str(x['id']) for x in data['relations']]),
                inline=True,
            )
        return embed

    async def prompt_user_about_similar_posts(self, ctx, similar_search_results):
        """Returns a tuple (continue?, relations_to_add)
        """
        for_member = ctx.author
        most_similar = sorted(
            similar_search_results['similarPosts'],
            key=itemgetter('distance')
        )
        # discord limits to 10 embeds:
        most_similar = most_similar[:10]
        embeds = {} # requiring ordered dicts here
        for pr in most_similar:
            pd = await self._augment_post_data(ctx, pr['post'])
            e = await self.post_data_to_embed(pd)
            # add similarity score:
            # TODO
            embeds[pr['post']['id']] = e

        class GenericButton(discord.ui.Button):
            async def callback(self, interaction: discord.Interaction):
                if interaction.user != for_member:
                    await interaction.response.send_message(
                        content=f"That menu is in use by someone else!",
                        ephemeral=True,
                        delete_after=10,
                    )
                    print(f"blocked other user interaction")
                    return
                await self.view.button_pressed(self, interaction)
                await interaction.response.defer()

        class SimilarPostPagingView(discord.ui.View):
            def __init__(self, ctx, post_embeds, *args, **kwargs):
                """post_embeds is dict key->embed"""
                super().__init__(*args, **kwargs)

                self.embed_pages = post_embeds
                self.cur_page = 0
                self.continue_upload = False
                self.selected_keys = []
                self.buttons = {}
                self.ctx = ctx
                self.msg = None

            async def start(self):
                # create buttons:
                buttons = {
                    'prev': ("Previous", "arrow_right"),
                    'toggle_relation': ("Add relation", "white_check_mark"),
                    'cancel': ("Cancel upload", "x"),
                    'next': ("Next", "arrow_left"),
                }
                for button_id, opts in buttons.items():
                    b = GenericButton(
                        custom_id=button_id,
                        label=opts[0],
                        # emoji=opts[1]
                    )
                    self.buttons[button_id] = b
                    self.add_item(b)
                self.buttons['prev'].disabled = True # on first page
                self.buttons['next'].disabled = len(self.embed_pages) <= 1
                self.msg = await self.ctx.send(
                    content=f"Found similar posts, please review:",
                    ephemeral=True,
                    embed=list(self.embed_pages.values())[0],
                    view=self,
                )
                return self.msg

            async def button_pressed(self, button, interaction):
                btn_id = button.custom_id

                if btn_id == 'prev':
                    if self.cur_page == 0:
                        # TODO no-op
                        pass
                    else:
                        self.cur_page -= 1
                elif btn_id == 'next':
                    if self.cur_page == len(self.embed_pages) - 1:
                        # TODO no-op
                        pass
                    else:
                        self.cur_page += 1
                elif btn_id == 'toggle_relation':
                    # which post?
                    post_id = list(self.embed_pages.keys())[self.cur_page]
                    if post_id in self.selected_keys:
                        self.selected_keys.remove(post_id)
                    else:
                        self.selected_keys.append(post_id)
                elif btn_id == 'cancel':
                    self.stop()
                    await self.msg.edit(
                        content=f"Upload cancelled.",
                        view=None, embed=None,
                    )
                    await self.msg.delete(delay=20)
                    return # do not proceed to below

                # update buttons and message:
                if btn_id in ['prev', 'next']:
                    if self.cur_page == 0:
                        self.buttons['prev'].disabled = True
                    else:
                        self.buttons['prev'].disabled = False
                    if self.cur_page == len(self.embed_pages) - 1:
                        self.buttons['next'].disabled = True
                    else:
                        self.buttons['next'].disabled = False
                cur_post = list(self.embed_pages.keys())[self.cur_page]
                if cur_post in self.selected_keys:
                    self.buttons['toggle_relation'].label = "Remove relation"
                else:
                    self.buttons['toggle_relation'].label = "Add relation"
                await self.msg.edit(
                    content=f"You pressed {btn_id}, on page {self.cur_page}, will add relations {self.selected_keys}",
                    embed=list(self.embed_pages.values())[self.cur_page],
                    view=self,
                )

        posts_view = SimilarPostPagingView(ctx, embeds)

        # start the initial message:
        msg = await posts_view.start()

        timed_out = await posts_view.wait()

        if timed_out:
            return (False, None)
        else:
            return (posts_view.continue_upload, posts_view.selected_keys)

    async def update_old_embed(self, ctx: commands.Context, old_message):
        if len(old_message.embeds) != 1:
            # Refusing to update old post message with unexpected number of embeds.
            return False
        first_embed = old_message.embeds[0]
        m = re.match(r'Post (?P<post_id>[0-9]+)', first_embed.title)
        if not m:
            # await ctx.reply(
            #     content="I couldn't figure out what post number that is, sorry."
            # )
            return False
        post_id = m.group('post_id')
        # get new embed:
        data = await self.get_post_by_id(ctx, post_id)
        post_e = await self.post_data_to_embed(data)
        await old_message.edit(
            embed=post_e,
        )
        return True

    ### NOTE Commands

    @commands.group(name='szuru', aliases=["sz"])
    async def szuru(self, ctx: commands.Context):
        """Base command for SzuruLink"""
        pass

    @szuru.group(name='set', aliases=["setting"])
    @commands.admin()
    async def szuru_set(self, ctx: commands.Context):
        """SzuruLink settings"""
        pass

    @szuru_set.command(name='url')
    async def set_api_url(self, ctx: commands.Context, *, api_url: str = None):
        if api_url:
            if api_url[-1] == '/':
                api_url = api_url[:-1]
            await ctx.cfg_channel.api_url.set(api_url)
            await ctx.send(f"Set API URL to `{api_url}`")
        else:
            api_url = await ctx.cfg_channel.api_url()
            await ctx.send(f"API URL is `{api_url}`")

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

    @szuru_set.command(name='exclude_unsafe', aliases=['skip_unsafe', 'excludeunsafe'])
    async def set_exclude_unsafe(self, ctx: commands.Context, not_a_bool: str = ""):
        """Set whether the autopost should exclude 'unsafe' posts or not
        """
        not_a_bool = not_a_bool.lower()
        # default with no arguments: set it to exclude
        if not_a_bool in ['true', 'yes', '1', 'exclude', '']:
            actually_a_bool = True
        else:
            actually_a_bool = False

        await ctx.cfg_guild.autopost_exclude_unsafe.set(actually_a_bool)
        if actually_a_bool:
            await ctx.send(f"Now unsafe posts will NOT be posted in this guild.")
        else:
            await ctx.send(f"Unsafe posts will be posted in this guild.")

    @szuru_set.command(name='postnum', aliases=['post'])
    async def set_post_number(self, ctx: commands.Context, post_num: int = 0):
        """
        Set the number of the latest post for autoposting.
        """
        await ctx.cfg_channel.current_post_num.set(post_num)
        await ctx.send("Current auto-post number has been set to {}".format(post_num))
        await ctx.cfg_channel.last_post_time.set(0)

    @szuru.command(name='login')
    async def user_login_process(self, ctx: commands.Context, user: str = None):
        """Login with this bot in order to upload content to the szuru via discord

        I will ask for an account token via DMs, so please ensure server member DMs are enabled, at least temporarily.
        I will try to delete your initial command containing your username once you've logged in successfully.
        """
        cu = await ctx.cfg_channel.api_url()
        if user is None:
            user = await ctx.cfg_member.szuruname()
            if user:
                await ctx.send(
                    f"{ctx.author.mention}: you're currently logged in as {user}, use `logout` to delete your credentials.",
                    delete_after=30,
                    reference=ctx.message,
                )
            else:
                await ctx.send(f"You're not currently logged into this szurubooru. Use `login <username>` to authenticate an account on {cu}")
        else:
            # interactive login process
            def token_check(message):
                if message.author == ctx.author:
                    return True
            promptmsg = await ctx.author.send(
                f"To complete the login process in {ctx.guild} please send me an account token generated from {cu}/user/{user}/list-tokens",
                delete_after=600,
            )
            tokenmsg = await self.bot.wait_for(
                'message',
                check=token_check,
                timeout=600
            )
            token = tokenmsg.content

            try:
                await ctx.cfg_member.szuruname.set(user)
                await ctx.cfg_member.szurutoken.set(token)
                profile = await self.user_api_login_bump(ctx)
                await ctx.author.send(
                    f"You're logged in as {profile['name']}! You should delete your message containing your token now.",
                )
                await ctx.send(f"{ctx.author.mention} logged in successfully!")
            except Exception as e:
                await ctx.cfg_member.szuruname.set(None)
                await ctx.cfg_member.szurutoken.set(None)
                await ctx.author.send(
                    f"Sorry, I could not authenticate you: {e}",
                )
                raise e
            finally:
                await ctx.message.delete()
                await promptmsg.delete()

    @szuru.command(name='register')
    async def user_registration_process(self, ctx: commands.Context, username: str = None):
        """Interactively register a new account on the szuru

        To ensure the privacy of the process, I will DM you to ask for more information. Please ensure server member DMs are enabled, at least temporarily.
        """
        raise NotImplementedError("Command not yet implemented!") # TODO

    @szuru.command(name='logout')
    async def user_logout_process(self, ctx: commands.Context):
        """Delete your szuru account info from this bot.

        You don't need to log out if you just need to change your token, simply run login again.
        """
        await ctx.cfg_member.szuruname.set(None)
        await ctx.cfg_member.szurutoken.set(None)
        await ctx.send(
            f"{ctx.author.mention}: you have been logged out, I no longer have access to your account.",
            reference=ctx.message,
        )

    @app_commands.command(name="upload")
    @app_commands.guild_only()
    @app_commands.describe(
        # safety="Safety rating for the post, required if the server has it enabled.",
        attachment="Attach the image/file to upload.",
    )
    async def upload_new_post_slash(
            self,
            #ctx: commands.Context,
            interaction: discord.Interaction,
            # safety: SzuruSafetyRating,
            #safety: typing.Literal['safe'],
            #tags: typing.Optional[str],
            attachment: typing.Optional[discord.Attachment],
        ):
        """Upload a post"""
        # await interaction.response.send_message(f"Workin on it...")
        await interaction.response.defer()
        ctx = await discord.ext.commands.Context.from_interaction(interaction)
        await self.update_interaction_context(interaction, ctx)

        # checking that there is something to upload:
        if not attachment:
            await interaction.followup.send(f"Sorry, I currently only support uploading via message attachments.")
            return
        else:
            # read file content
            filebytes = await attachment.read()
            filetokenresp = await self.user_api_upload_tempfile(ctx, filebytes)
            img_tempurl = attachment.url

        relations = []
        # search for similar
        similar_search_results = await self.user_api_post(
            ctx, "/posts/reverse-search",
            json_data={
                "contentToken": filetokenresp['token'],
            }
        )
        if similar_search_results['exactPost']:
            await interaction.followup.send(
                content=f"Looks like that is already uploaded!",
            )
            # TODO show existing post
            return
        elif similar_search_results['similarPosts']:
            should_continue, relations = await self.prompt_user_about_similar_posts(
                ctx, similar_search_results
            )
            if not should_continue:
                print(f"should not continue after similar search")
                return

        if True: #enableSafety
            safety_prompt = SzuruPostUploadSafetyPrompt()
            e = discord.Embed().set_image(
                url=img_tempurl
            )
            msg = await interaction.followup.send(
                content=f"Choose a safety rating",
                view=safety_prompt,
                ephemeral=True,
                wait=True, # returns msg
                embed=e,
            )
            timed_out = await safety_prompt.wait()
            if timed_out:
                await msg.edit(content=f"Interaction timed out.", view=None, embed=None)
                return
            selected_safety = safety_prompt.children[0].values[0]
            await msg.edit(
                content=f"Selected safety {selected_safety}.",
                view=None,
                embed=None,
            )
            await msg.delete(delay=20)

        uploading_message = await interaction.followup.send(
            content="Uploaderin...", wait=True,
        )

        # TODO, change temp upload to post

    @szuru.command(name='upload', aliases=['u'])
    async def upload_new_post(
            self,
            ctx: commands.Context,
            safety: typing.Literal['safe', 'sketchy', 'unsafe'],
            *tags):
        """Upload media to the szuru via discord

        Specify 'anon' or 'anonymous' after the safety to upload anonymously.
        To upload via URL, first ensure you have permission on the site to use the URL uploader. (Check for a URL box on the upload page.)
        """
        safety = safety.lower()
        if safety not in ['safe', 'sketchy', 'unsafe']:
            raise ValueError(f"Must specify safety: safe, sketchy, or unsafe")
        anon = False
        urls = []
        sources = []
        tags = list(tags)
        if 'anonymous' in tags:
            anon = True
            tags.remove('anonymous')
        if 'anon' in tags:
            anon = True
            tags.remove('anon')
        for tag in tags:
            if '://' in tag:
                url = tag.strip('<>')
                urls.append(url)
                tags.remove(tag)

        if not ctx.message.attachments and not urls:
            raise ValueError(f"Please attach the media to upload to your discord message!")
        if len(urls) > 1:
            await ctx.send(f"Notice: Only one post will be created per command, assuming multiple URLs are all sources for the same media.")

        if urls:
            sources += urls
        if not anon:
            sources.append(ctx.message.jump_url)

        # communicating with the szuru / waiting work
        async with ctx.typing():
            # Checks to see if any of the tags being uploaded has implied tags that should also be applied to the post.
            for tag in tags:
                tagDL = await self.api_get(ctx, f"/tag/{tag}")
                if 'name' in tagDL and tagDL['name'] == "TagNotFoundError":
                    print(f"sz: New Tag: {tag}")
                else:
                    for implied_tag in tagDL['implications']:
                        tags.append(implied_tag['names'][0])

            jdata = {
                "safety": safety,
                "tags": tags,
                "anonymous": anon,
                "source": '\n'.join(sources)
            }

            try:
                if ctx.message.attachments:
                    filebytes = await ctx.message.attachments[0].read()
                    filetokenresp = await self.user_api_upload_tempfile(ctx, filebytes)
                elif urls:
                    # get image via URL, get token for it
                    try:
                        filetokenresp = await self.user_api_post(
                            ctx, f"/uploads",
                            json_data={
                                "contentUrl": urls[0],
                            }
                        )
                    except aiohttp.client_exceptions.ClientResponseError as e:
                        raise ValueError(f"Could not upload! The server could not / is not able to handle that.")
                else:
                    raise ValueError(f"You didn't give me something to upload!")
            except SzuruLinkUserNotLoggedIn as e:
                raise SzuruLinkUserNotLoggedIn(f"You need to be logged in to upload posts!")
            print(f"file token: {filetokenresp}")
            jdata["contentToken"] = filetokenresp['token']
            # TODO check image similarity

            # print(jdata)
            rdata = await self.user_api_post(
                ctx, f"/posts/",
                json_data=jdata,
            )
            # print(rdata)

            data = await self._augment_post_data(ctx, rdata)
            post_e = await self.post_data_to_embed(data, include_image=False)
            await ctx.send(
                f"Uploaded!",
                reference=ctx.message,
                embed=post_e,
            )
            # update user's "last seen"
            await self.user_api_login_bump(ctx)

    @szuru.command(name='post', aliases=['p'])
    async def get_post(self, ctx: commands.Context, postid: int):
        """Get a post by ID"""
        async with ctx.typing():
            data = await self.get_post_by_id(ctx, postid)
            post_e = await self.post_data_to_embed(data)
            attach = await self.get_file_from_post_data(data)

            await ctx.send(
                data['_']["message_content"] if not data['_']["should_embed"] else None,
                embed=post_e,
                # file=attach,
            )

    @szuru.command(name='tag', aliases=['t', 'tags'])
    async def szuru_tag(self, ctx: commands.Context, postid: int, operation: str, *tags):
        """Modify tags on a post by ID

        Must be logged in to edit post tags.
        Prefix a tag with `-` (minus / dash) to remove that tag.
        Apply operation to multiple posts by separating post IDs with a comma. (`,`)
        """
        raise NotImplementedError(f"Work in progress!") # TODO

    @szuru.command(name='search', aliases=['query', 'find', 'f', 's'])
    async def search_posts(self, ctx: commands.Context, *query):
        """Search posts by query"""
        async with ctx.typing():
            print(query)
            qstr = ' '.join(query)
            search_results = await self.get_posts_by_query(ctx, qstr)

            await ctx.send(
                f"Found {search_results['total']} results:",
                # files=[
                #     await self.get_file_from_post_data(d) for d in search_results['_']['results'][:3]
                # ],
            )
            max = await self.config.max_searchresults()

            for data in search_results['_']['results'][:max]:
                # data = await self.get_post_by_id(ctx, postid)
                post_e = await self.post_data_to_embed(data)
                attach = await self.get_file_from_post_data(data)
                await ctx.send(
                    data['_']["message_content"] if not data['_']["should_embed"] else None,
                    embed=post_e,
                    # file=attach,
                )

            if search_results['total'] > max:
                await ctx.send("To see more results either refine the search or change the sorting order.")

    @szuru.command(name='update', aliases=['refresh'])
    async def update_post_embed(self, ctx: commands.Context):
        """Update the embed of a previously sent message."""
        if not ctx.message.reference:
            await ctx.reply(
                content="Reply to one of my own messages when using this command, and I'll do my best to update that old embed!",
                delete_after=60,
            )
            await ctx.message.delete(delay=60)
            return
        async with ctx.typing():
            ref_message = ctx.message.reference.resolved
            if not ref_message.embeds:
                await ctx.reply(
                    content="I couldn't update that message! I didn't find any embeds in it!"
                )
                return
            if await self.update_old_embed(ref_message):
                await ctx.tick()

    # can't use cog-style here: https://github.com/Rapptz/discord.py/issues/7823#issuecomment-1086830458
    # @app_commands.context_menu(name="Update Post Embed")
    async def update_post_embed_by_context_menu(self, interaction: discord.Interaction, msg: discord.Message):
        if msg.author != self.bot.user:
            await interaction.response.send_message("I can only update my own messages!", ephemeral=True)
            return
        if len(msg.embeds) != 1:
            await interaction.response.send_message("I am not sure how to update that post.", ephemeral=True)
            return
        ctx = await discord.ext.commands.Context.from_interaction(interaction)
        await self.update_interaction_context(interaction, ctx)

        updated = await self.update_old_embed(ctx, msg)
        if not updated:
            await interaction.response.send_message("Sorry, I could parse that embed.", ephemeral=True)
            return
        else:
            await interaction.response.send_message(f"Updated {msg.jump_url}!", ephemeral=True)

    @szuru.command(name='massupdate', aliases=[])
    @discord.ext.commands.is_owner()
    async def mass_update_old_post_embeds(self, ctx: commands.Context, count: int=50, before=None):
        """Update many old embeds with one command.

        This can easily break your discord API rate limit for huge instances,
        so only the bot owner can use this command.
        """
        ch = ctx.message.channel
        async with ctx.typing():
            if not before:
                if ctx.message.reference:
                    before = ctx.message.reference.resolved
                else:
                    before = ctx.message
            else:
                raise NotImplementedError()
            progress_msg = await ctx.reply(
                content=f"Checking the last {count} messages in this channel before {before.jump_url}"
            )
            n_updated = 0
            failed = []
            n_scanned = 0
            async for msg in ch.history(limit=count, before=before):
                n_scanned += 1
                if msg.author != self.bot.user:
                    continue
                if len(msg.embeds) != 1:
                    continue
                updated = await self.update_old_embed(ctx, msg)
                if updated:
                    n_updated += 1
                else:
                    failed.append(msg)
                await progress_msg.edit(
                    content=f"messages updated {n_updated} / scanned {n_scanned} ...",
                )
            await progress_msg.edit(
                content=f"Updated {n_updated} out of {n_scanned} scanned messages before {before.jump_url}.",
                suppress=True,
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

            ctx = dotdict()
            ctx.cfg_channel = cfg_channel
            ctx.cfg_guild = cfg_guild
            try:
                data = await self.get_post_by_id(ctx, last_post_id + 1)
                # check should skip post
                unsafe = True if data['safety'] == "unsafe" else False
                if unsafe:
                    should_exclude_unsafe = await cfg_guild.autopost_exclude_unsafe()
                    if should_exclude_unsafe:
                        # skip this post
                        await cfg_channel.current_post_num.set(last_post_id + 1)
                        continue
                post_e = await self.post_data_to_embed(data)
                attach = await self.get_file_from_post_data(data)
                await ch.send(
                    data['_']["message_content"] if not data['_']["should_embed"] else None,
                    embed=post_e,
                )
                await cfg_channel.last_post_time.set(now)
                await cfg_channel.current_post_num.set(last_post_id + 1)
            except LookupError as e:
                # check if there are further posts (i.e. missing number)
                search_results = await self.get_posts_by_query(ctx, "sort:date")
                latest_id = search_results['_']['results'][0]['id']
                if latest_id > last_post_id:
                    await cfg_channel.current_post_num.set(last_post_id + 1)
                continue

    @check_send_next_post.before_loop
    async def check_send_next_post_wait(self):
        await self.bot.wait_until_ready()

    # @commands.Cog.listener('on_message')
    # async def on_message(self, message):
    #     if message.content in e_qs.keys():
    #         await message.reply(e_qs[message.content])
