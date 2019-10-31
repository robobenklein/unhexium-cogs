from .hexevents import HexEvents
import asyncio

async def setup(bot):
    obj = bot.add_cog(HexEvents(bot))
    if asyncio.iscoroutine(obj):
        await obj
