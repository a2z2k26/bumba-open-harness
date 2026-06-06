"""Job board scrapers."""
from .base import JobBoard, JobListing
from .weworkremotely import WeWorkRemotelyBoard
from .remoteok import RemoteOKBoard
from .remotive import RemotiveBoard
from .himalayas import HimalayasBoard
from .jobicy import JobicyBoard
from .workingnomads import WorkingNomadsBoard
from .builtin import BuiltInBoard
from .yc_workatastartup import YCombinatorBoard
from .dribbble import DribbbleBoard
from .behance import BehanceBoard
from .coroflot import CoroflotBoard
from .nodesk import NodeskBoard
from .dice import DiceBoard
from .stubs import (
    IndeedBoard,
    LinkedInBoard,
    GlassdoorBoard,
    FlexjobsBoard,
    TheLaddersBoard,
    OttaBoard,
    RemoteCoBoard,
    IxdaBoard,
    PangianBoard,
    LetsWorkRemotelyBoard,
    SkipTheDriveBoard,
    SonaraBoard,
    PathriseBoard,
    TalentpriseBoard,
    PyjamaBoard,
    OpenJobsAIBoard,
    OfferedBoard,
    WisefulBoard,
)

__all__ = [
    "JobBoard",
    "JobListing",
    "WeWorkRemotelyBoard",
    "RemoteOKBoard",
    "RemotiveBoard",
    "HimalayasBoard",
    "JobicyBoard",
    "WorkingNomadsBoard",
    "BuiltInBoard",
    "YCombinatorBoard",
    "DribbbleBoard",
    "BehanceBoard",
    "CoroflotBoard",
    "NodeskBoard",
    "DiceBoard",
    "IndeedBoard",
    "LinkedInBoard",
    "GlassdoorBoard",
    "FlexjobsBoard",
    "TheLaddersBoard",
    "OttaBoard",
    "RemoteCoBoard",
    "IxdaBoard",
    "PangianBoard",
    "LetsWorkRemotelyBoard",
    "SkipTheDriveBoard",
    "SonaraBoard",
    "PathriseBoard",
    "TalentpriseBoard",
    "PyjamaBoard",
    "OpenJobsAIBoard",
    "OfferedBoard",
    "WisefulBoard",
]
