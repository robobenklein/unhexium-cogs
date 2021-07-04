
# SzuruLink RedBot Cog

A Discord RedBot cog that enables interaction with a SzuruBooru instance.

Features:

- Auto-post new uploads to a specific channel on a timer (only one auto-post channel per guild supported)
- Display posts directly by number
- Search posts by tags
- Users can login via the bot and upload images directly from Discord via message attachment or a direct URL.

Potential future plans: (if you want one of these implemented let me know)

- Modify post tags
- Upload posts by replying to a message with an image or reacting with a specific emote
- Allow user registration via the bot itself
- Enable multiple auto-post channels (you can already have different channels use different szurubooru instances)

## Install

Install RedBot (https://docs.discord.red/en/stable/index.html)

Enable the downloader cog: `[p]load downloader` (`[p]` is your prefix)

Add this cog repo: `[p]repo add unhexium-cogs https://github.com/robobenklein/unhexium-cogs.git`

Install this cog: `[p]cog install unhexium-cogs szurulink`

Load it: `[p]load szurulink`

Now you can set up access to your booru instance: you'll need the URL, a user for the bot, and an access token for that account. (These are stored per-channel, so you need to perform this setup in the desired channel.)

Set your instance url: `[p]sz set url https://your-cool-szuru.is_dumb`

Set the bot account username: `[p]sz set user my_bot_user`

Set the bot's access token: `[p]sz set token f795dd1f-25ac-421e-bf56-281b68600bce` (you can get this from the account page > login tokens > Create token)

Done! You should now be able to view the first post: `[p]sz post 1`

## Auto-posting Channel

You can configure the bot to automatically post uploads to a channel. First ensure you can use the `post` command to view posts there normally.

Set the timer (how long between each posting): `[p]sz set time 600` (number of seconds, 600=10min, default is 1hr/3600)

Set the channel to post to `[p]sz set channel #your-cool-szuru-channel`

Done! The bot will now check the szuru for a new post at least once a minute, and post it to the channel automatically.
