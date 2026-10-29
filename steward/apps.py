"""Which apps the steward may read.

Only Rui Codex's own apps. Two classes are excluded by owner decision (2026-10-18):

* health-related apps, whose reviews can carry special-category data (GDPR Art. 9);
* apps whose code was written by someone outside Rui Codex.

The exclusion is enforced here, in one place, and every connector asks `is_included` before it
reads anything. The reason travels with the entry so a report can say why an app is absent.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class App:
    package: str
    name: str
    kind: str              # "game" or "app"
    excluded: str = ""      # empty = included; otherwise the reason


APPS: tuple[App, ...] = (
    App("com.ruicodex.IdleFactoryTycoon", "Idle Factory Tycoon", "game"),
    App("com.ruicodex.idledefense", "Idle Defense", "game"),
    App("com.ruicodex.starharbor", "Star Harbor", "game"),
    App("com.ruicodex.koidrift", "Koi Drift", "game"),
    App("com.ruicodex.lumenloop", "Lumen Loop", "game"),
    App("com.ruicodex.gravity_block_flip", "Gravity Block Flip", "game"),
    App("com.ruicodex.gravity_desert_flip", "Gravity Desert Flip", "game"),
    App("com.ruicodex.ant_empire", "Ant Empire", "game"),
    App("com.ruicodex.candychaos", "Candy Chaos", "game"),
    App("com.ruicodex.luckyballoon", "Lucky Balloon", "game"),
    App("com.ruicodex.pullplunder", "Pull Plunder", "game"),
    App("com.ruicodex.quiltvale", "Quiltvale", "game"),
    App("com.ruicodex.grandmaskitchen", "Grandma's Kitchen", "game"),
    App("com.ruicodex.titantakeout", "Titan Takeout", "game"),
    App("com.ruicodex.ringflip", "Ring Flip", "game"),
    App("com.ruicodex.stickmanempire", "Stickman Empire", "game"),
    App("com.ruicodex.cipherdepths", "Cipher Depths", "game"),
    App("com.ruicodex.rhythmpulse", "Rhythm Pulse", "game"),
    App("com.ruicodex.voidrunner", "Void Runner", "game"),
    App("com.ruicodex.towervanguard", "Tower Vanguard", "game"),
    App("com.ruicodex.neontactics", "Neon Tactics", "game"),
    App("com.ruicodex.mergekingdom", "Merge Kingdom", "game"),
    App("com.ruicodex.galaxyfoundry", "Galaxy Foundry", "game"),
    App("com.ruicodex.blockfallsaga", "Blockfall Saga", "game"),
    App("com.ruicodex.last_base_defense", "Last Base Defense", "game"),
    App("com.altinayselman.standbyclock", "StandBy Clock", "app"),
    App("com.ruicodex.florea", "Florea", "app"),
    App("com.ruicodex.letslearn", "LetsLearn", "app"),
    App("com.ruicodex.pixelcut_pro", "PixelCut Pro", "app"),
    App("com.altinayselman.belgeokuyucu", "Document Reader", "app"),
    App("com.ruicodex.whatshouldiwear", "What Should I Wear", "app"),
    App("com.ruicodex.invitequick", "InviteQuick", "app"),
    App("com.ruicodex.colornest", "ColorNest", "app"),
    App("com.ruicodex.radiosem", "RadioSEM", "app"),
    # Excluded: health-related (owner decision #2, brief 2026-10-26).
    App("com.ruicodex.dietsem", "DietSEM", "app", excluded="health"),
    App("com.ruicodex.juju", "Juju", "app", excluded="health"),
    App("com.ruicodex.serenacare", "Serena Care", "app", excluded="health"),
    App("com.ruicodex.fitlife", "FitLife", "app", excluded="health"),
    # Excluded: code written outside Rui Codex (owner decision #2 of 2026-10-18).
    App("com.everytranslate.app", "EveryTranslate", "app", excluded="third-party-authored"),
    App("com.ruicodex.posterboost.ai", "PosterBoost", "app", excluded="third-party-authored"),
)

_BY_PACKAGE = {a.package: a for a in APPS}


def get(package: str) -> App | None:
    return _BY_PACKAGE.get(package)


def is_included(package: str) -> bool:
    """Unknown packages are refused: the default points at exclusion, never at inclusion."""
    app = _BY_PACKAGE.get(package)
    return app is not None and not app.excluded


def included() -> list[App]:
    return [a for a in APPS if not a.excluded]


def excluded() -> list[App]:
    return [a for a in APPS if a.excluded]
