
from .auto_prune_members import AutoPruneMembers

def setup(bot):
    bot.add_cog(AutoPruneMembers(bot))
