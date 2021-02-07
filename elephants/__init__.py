
from .elephant import ElephantResponder

def setup(bot):
    bot.add_cog(ElephantResponder(bot))
