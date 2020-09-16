import os
import sys

from src.bot import Salamander

if __name__ == "__main__":
    if TOKEN := os.environ.get("SALAMANDER_TOKEN", None):
        Salamander.run_with_wrapping(TOKEN)
    else:
        sys.exit("No token?")
