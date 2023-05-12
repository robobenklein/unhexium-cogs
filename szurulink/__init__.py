
from .szurulink import SzuruPoster

async def setup(bot):
    await bot.add_cog(SzuruPoster(bot))
