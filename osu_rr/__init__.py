
from .osu_rr import OsuRankReporter

def setup(bot):
    bot.add_cog(OsuRankReporter(bot))
