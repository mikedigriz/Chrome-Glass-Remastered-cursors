"""Where everything lives, in one place.

Every other module in this package used to anchor on `HERE = dirname(__file__)`
and mean "the repository" by it. That stopped being true when the modules moved
into cgr/, and spreading `dirname(dirname(...))` across five files is worse than
one module that states the layout once.
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(ROOT, "art")           # reference frames: orig, ai, ai512, aialpha
DATA = os.path.join(ROOT, "data")         # traced.json, metrics-*.json
ASSETS = os.path.join(ROOT, "assets")     # preview.png, animated webp/gif
TOOLS = os.path.join(ROOT, "tools")
DOCS = os.path.join(ROOT, "docs")
DEV_DOCS = os.path.join(DOCS, "dev")      # the working journals, not shipped docs
WEIGHTS = os.path.join(ROOT, "weights")   # Real-ESRGAN checkpoints, gitignored
