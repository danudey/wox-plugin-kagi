import os
import sys

# Add dependencies directory to Python path
deps_dir = os.path.join(os.path.dirname(__file__), "dependencies")
if deps_dir not in sys.path:
    sys.path.insert(0, deps_dir)

from main import plugin

__all__ = ["plugin"]
