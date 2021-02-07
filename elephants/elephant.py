
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

e_qs = {
    "Q: Why do elephants paint their toenails red?": "A: So they can hide in cherry trees.",
    "Q: Have you ever seen an elephant in a cherry tree?": "A: (they will say NO). Works, doesn't it?!",
    "Q: How do you know there have been elephants in the fridge?": "A: There's footprints in the butter.",
    "Q: Why do elephants paint their ears yellow?": "A: That's not paint, its butter.",
    "Q: Why do elephants paint their toenails red, blue, green, orange, yellow, and brown?": "A: So they can hide in a bag of M&Ms.",
    "Q: How did the pygmie break his back?": "A: He tried to carry a bag of M&Ms home from the store.",

    "Q: Why is it dangerous to walk in the jungle between 3 and 4 in the afternoon?": "A: That's when the elephants jump out of the trees.",
    "Q: Why are pygmies so small?": "A: They walked in the jungle between 3 and 4 in the afternoon.",

    "Q: How do you get an elephant on top of an oak tree?": "A: Stand him on an acorn and wait fifty years.",
    "Q: What if you don't want to wait fifty years?": "A: Parachute him from an airplane.",
    "Q: Why isn't it safe to climb oak trees between 1 and 2 in the afternoon?": "A: Because that is when the elephants practice their parachute jumping.",

    "Q: Why are elephants feet shaped that way?": "A: To fit on lily pads.",
    "Q: Why isn't it safe to walk on the lily pads between 4 and 5 in the afternoon?": "A: That's when the elephants are walking on the lily pads.",
    "Q: Why are frogs such good jumpers?": "A: So they can walk on the lily pads between 4 and 5 in the afternoon.",

    "Q: How do you get two elephants in a pickup truck?": "A: One in the cab, one in the back.",
    "Q: How do you get two mice in a pickup truck?": "A: You can't ... it's full of elephants.",

    "Q: Why do ducks have flat feet?": "A: From stomping out forest fires!",
    "Q: Why do elephants have flat feet?": "A: From stomping out burning ducks!",

    "Q: What did Tarzan say when he saw a herd of elephants running through the jungle?": "A: 'Here come the elephants running through the jungle!'",
    "Q: Why did the elephants wear sunglasses?": "A: So Tarzan wouldn't recognize them.",
    "Q: What did Tarzan say when he saw a herd of elephants running through the jungle?": "A: Nothing. He didn't recognize them with their sunglasses on.",
    "Q: What did Tarzan say when he saw a herd of giraffes in the distance?": "A: 'Haha! You fooled me once with those disguises, but not this time!'",
    "Q: What is the difference between en elephant and a plum?": "A: An elephant is grey.",
    "Q: What did Jane say when she saw a herd of elephants in the distance?": "A: 'Look! A herd of plums in the distance' (Jane is color blind)",

    "Q: Why do cub scouts run so fast in the forest at night?": "A: To escape the elephants swinging through the trees.",
    "Q: What's that yucky stuff between the elephant's toes?": "A: Slow cub scouts!",

    "Q: How can you tell if an elephant is under your bed?": "A: The ceiling is very close!",
    "Q: How do you know if there's an elephant in bed?": "A: He has a big 'E' on his pajamas jacket pocket.",
    "Q: How do you tell an elephant from a field mouse?": "A: Try to pick it up, If you can't, it's either an elephant or a very overweight field mouse.",
    "Q: How can you tell if an elephant has been in the refrigerator?": "A: Footprints in the Jell-O.",
    "Q: How can you tell if there are 2 elephants in the refrigerator?": "A: You can't shut the door!",
    "Q: How do you get an elephant into the fridge?": """1. Open door.
2. Insert elephant.
3. Close door.""",

    "Q: How do you get a giraffe into the fridge?": """1. Open door.
2. Remove elephant.
3. Insert giraffe.
4. Close door.""",
    "Q: The lion, the king of the jungle, decided to have a party. He invited all the animals in the jungle, and they all came except one. Which one?": "A: The giraffe, because he was still in the fridge.",
    "Q: How do you know Tarzan is in the fridge?": "A: You can hear Tarzan scream OYOYOYOIYOIYOOOOOO",
    "Q: How do you get two Tarzans in the fridge?": "A: You can't, silly. There is only one Tarzan!",
    "Q: How do you get 4 elephants into a Volkswagen?": "A: 2 in the front and 2 in the back",
    "Q: How do you know if there are 4 elephants in your fridge?": "A: There's a VW parked outside it.",
    "Q: What did the fifth elephant in the VW discover?": "A: The sun roof.",
    "Q: Why are there so many elephants running around free in the jungle?": "A: The fridge isn't large enough to hold them all.",

    "Q: How do you get an elephant out of the water?": "A: Wet.",
    "Q: How do you get two elephants out of the water?": "A: One by one.",

    "Q: How do you shoot a blue elephant?": "A: With a blue elephant gun, of course.",
    "Q: How do you shoot a yellow elephant?": "A: There's no such thing as yellow elephants.",

    "Q: Why did the elephant fall out of the tree?": "A: Because it was dead.",
    "Q: Why did the second elephant fall out of the tree?": "A: It was glued to the first one.",
    "Q: Why did the third elephant fall out of the tree?": "A: It thought it was a game.",
    "Q: And why did the tree fall down?": "A: It thought it was an elephant.",

    "Q: Why do elephants wear sandals?": "A: So that they don't sink in the sand.",
    "Q: Why do ostriches stick their head in the ground?": "A: To look for the elephants who forgot to wear their sandals.",

    "Q: What did the elephant say when he saw a dead ant on the road?": "A: Deadant, Deadant, Deadant! (sung to Pink Panther tune).",
    "Q: What did the elephant say when he saw a live ant on the road?": "A: He stomped on it and then said 'Deadant, Deadant, Deadant!'.",

    "Q: Why did the elephant stand on the marshmallow?": "A: He didn't want to sink in the hot chocolate.",
    "Q: How do elephants keep in touch over long distances?": "A: They make trunk calls.",
    "Q: What's red and white on the outside and gray and white on the inside?": "A: Campbell's Cream of Elephant soup.",
    "Q: How do you smuggle an elephant across the border?": "A: Put a slice of bread on each side, and call him 'lunch'.",
    "Q: Why are elephants wrinkled?": "A: Have you ever tried to iron one?",
    "Q: Why did the elephant cross the road?": "A: Chicken's day off.",
    "Q: What do you call two elephants on a bicycle?": "A: Optimistic!",
    "Q: What do you get if you take an elephant into the city?": "A: Free Parking.",
    "Q: What do you get if you take an elephant into work?": "A: Sole use of the elevator.",
    "Q: How do you know if there is an elephant in the bar?": "A: It's bike is outside.",
    "Q: How do you know if there are three elephants in the bar?": "A: Stand on the bike and have a look in the window.",
    "Q: Why do elephants wear tiny green hats?": "A: To sneak across a pool table without being seen.",
    "Q: How many elephants does it take to change a light bulb?": "A: Don't be stupid, elephants can't change light bulbs.",
    "Q: What do you get if you cross an elephant with a whale?": "A: A submarine with a built-in snorkel.",
    "Q: How do you make a dead elephant float?": "A: Well, you take 10 dead elephants, 10 tons of chocolate ice-cream, 5 tons of bananas,.....",
    "Q: What do you know when you see three elephants walking down the street wearing pink sweatshirts?": "A: They're all on the same team.",
    "Q: How do you stop an elephant from charging?": "A: Take away his credit card.",
    "Q: Why do elephants have trunks?": "A: Because they would look silly with glove compartments.",
    "Q: What do you give a seasick elephant?": "A: Lots of room.",
    "Q: What has two tails, two trunks and five feet?": "A: An elephant with spare parts",
    "Q: What's grey and puts out forest fires?": "A: Smokey the Elephant.",
    "Q: What happens when an elephant sits in front of you at the movies?": "A: You miss most of the picture!",
    "Q: What did the peanut say to the elephant?": "A: Nothing, peanuts can't talk.",
    "Q: How do you know when an Elephant has been in the baby carriage?": "A: By the footprints on the baby's forehead!",
    "Q: What is beautiful, gray and wears glass slippers?": "A: Cinderelephant.",

    "Q: What time is it when an elephant sits on your fence?": "A: 6:15PM (trick question!)",

    "Q: How do you shoot a blue elephant?": "A: With a blue elephant gun.",
    "Q: How do you shoot a white elephant?": "A: Hold his nose until he turns blue, then shoot him with a blue elephant gun.",
}


class ElephantResponder(commands.Cog):
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
        if message.content in e_qs.keys():
            await message.reply(e_qs[message.content])
