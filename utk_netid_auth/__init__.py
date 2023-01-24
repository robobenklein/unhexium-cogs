
from .utk_netid_auth import UtkNetidAuth

# Red v3.5+
async def setup(bot):
    await bot.add_cog(UtkNetidAuth(bot))
