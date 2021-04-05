
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

import discord
from async_timeout import timeout
from discord.ext import tasks
import requests
import aiohttp

from redbot.core import commands
from redbot.core import Config, commands, checks
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import pagify, warning, box
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
        "max_searchresults": 3,
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

        self.check_send_next_post.start()

    # def cog_unload(self):
    #     for state in self.voice_states.values():
    #         self.bot.loop.create_task(state.stop())
    #
    #     return state

    def cog_unload(self):
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

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send('SzuruLink: do you have permission to do that?')
        elif isinstance(error, aiohttp.client_exceptions.ClientResponseError):
            await ctx.send(f'SzuruLink: server error: {error}')
            print(f"error {error}")
            print(f"request: {error.request_info}")
            # print(f"")
            raise error
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
        auth = stringToBase64(f"{api_user}:{api_token}")

        r = await self.session.post(
            f"{au}{path}",
            headers={
                'Authorization': f"Token {auth}",
                # 'Content-Type': 'application/json',
                'Accept': 'application/json',
            },
            json=json_data,
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
        data['_'] = {
            "media_url": f"{cu}/{data['contentUrl']}",
            "post_url": f"{cu}/post/{data['id']}",
            "embed_visible": False if data['type'] == 'video' else True,
            "unsafe": unsafe,
            "filename": data['contentUrl'].split('/')[-1],
            "user": None,
        }
        if 'user' in data and data['user']:
            data['_']["user"] = {
                "icon_url": f"{cu}/{data['user']['avatarUrl']}",
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
            embed.add_field(
                name="Tags",
                value=', '.join([
                    f"{x['names'][0]} ({x['usages']})"
                    for x in data['tags']
                ]),
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

    @szuru.command(name='upload', aliases=['u'])
    async def upload_new_post(self, ctx: commands.Context, safety: str, *tags):
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

        jdata = {
            "safety": safety,
            "tags": tags,
            "anonymous": anon,
            "source": '\n'.join(sources)
        }

        # communicating with the szuru / waiting work
        async with ctx.typing():
            if ctx.message.attachments:
                filebytes = await ctx.message.attachments[0].read()
                filetokenresp = await self.user_api_upload_tempfile(ctx, filebytes)
            elif urls:
                # get image via URL, get token for it
                filetokenresp = await self.user_api_post(
                    ctx, f"/uploads",
                    json_data={
                        "contentUrl": urls[0],
                    }
                )
            else:
                raise ValueError(f"You didn't give me something to upload!")
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
            post_e = await self.post_data_to_embed(data)
            await ctx.send(
                f"Uploaded!",
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
                    embed=post_e,
                    # file=attach,
                )

            if search_results['total'] > max:
                await ctx.send("To see more results either refine the search or change the sorting order.")

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
                post_e = await self.post_data_to_embed(data)
                attach = await self.get_file_from_post_data(data)
                await ch.send(
                    # f"Auto-Post:",
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
