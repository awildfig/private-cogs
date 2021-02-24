from .soccer import Soccer
from redbot.core.bot import Red

def setup(bot: Red):
    bot.add_cog(Soccer(bot))