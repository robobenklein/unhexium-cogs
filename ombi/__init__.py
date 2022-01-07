
from .red_ombi_requester import RedOmbiRequester

def setup(bot):
    bot.add_cog(RedOmbiRequester(bot))
