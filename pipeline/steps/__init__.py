"""Pipeline steps, in execution order.

A step exposes `NAME`, `VERSION`, `params(cfg)` and `run(ws, cfg, log) -> summary dict`.
The runner records its status in paper.json and skips it when it already finished
with the same version and parameters (unless forced).
"""

from . import s0_preprocess, s1_locate, s2_extract

STEPS = {
    s0_preprocess.NAME: s0_preprocess,
    s1_locate.NAME: s1_locate,
    s2_extract.NAME: s2_extract,
}
