"""Tests for board scrapers — mocked HTTP + parse logic for all boards."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from job_search.boards.base import JobBoard

# All board imports for instantiation tests
from job_search.boards.remotive import RemotiveBoard
from job_search.boards.himalayas import HimalayasBoard
from job_search.boards.jobicy import JobicyBoard
from job_search.boards.remoteok import RemoteOKBoard
from job_search.boards.workingnomads import WorkingNomadsBoard
from job_search.boards.weworkremotely import WeWorkRemotelyBoard
from job_search.boards.yc_workatastartup import YCombinatorBoard
from job_search.boards.dribbble import DribbbleBoard
from job_search.boards.behance import BehanceBoard
from job_search.boards.coroflot import CoroflotBoard
from job_search.boards.builtin import BuiltInBoard
from job_search.boards.nodesk import NodeskBoard
from job_search.boards.dice import DiceBoard
from job_search.boards.stubs import (
    IndeedBoard, LinkedInBoard, GlassdoorBoard, FlexjobsBoard,
    TheLaddersBoard, OttaBoard, RemoteCoBoard, IxdaBoard,
    PangianBoard, LetsWorkRemotelyBoard, SkipTheDriveBoard,
    SonaraBoard, PathriseBoard, TalentpriseBoard, PyjamaBoard,
    OpenJobsAIBoard, OfferedBoard, WisefulBoard,
)

ALL_BOARD_CLASSES = [
    RemotiveBoard, HimalayasBoard, JobicyBoard, RemoteOKBoard,
    WorkingNomadsBoard, WeWorkRemotelyBoard, YCombinatorBoard,
    DribbbleBoard, BehanceBoard, CoroflotBoard, BuiltInBoard,
    NodeskBoard, DiceBoard,
    IndeedBoard, LinkedInBoard, GlassdoorBoard, FlexjobsBoard,
    TheLaddersBoard, OttaBoard, RemoteCoBoard, IxdaBoard,
    PangianBoard, LetsWorkRemotelyBoard, SkipTheDriveBoard,
    SonaraBoard, PathriseBoard, TalentpriseBoard, PyjamaBoard,
    OpenJobsAIBoard, OfferedBoard, WisefulBoard,
]

STUB_BOARDS = [
    IndeedBoard, LinkedInBoard, GlassdoorBoard, FlexjobsBoard,
    TheLaddersBoard, OttaBoard, RemoteCoBoard, IxdaBoard,
    PangianBoard, LetsWorkRemotelyBoard, SkipTheDriveBoard,
    SonaraBoard, PathriseBoard, TalentpriseBoard, PyjamaBoard,
    OpenJobsAIBoard, OfferedBoard, WisefulBoard,
]


# ── Helpers ──

WWR_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>We Work Remotely</title>
    <item>
      <title>Stripe: Senior Software Engineer</title>
      <link>https://weworkremotely.com/jobs/1</link>
      <region>USA Only</region>
    </item>
    <item>
      <title>Airbnb: Marketing Manager</title>
      <link>https://weworkremotely.com/jobs/2</link>
      <region>Worldwide</region>
    </item>
  </channel>
</rss>"""

REMOTEOK_JSON = [
    {"legal": "remoteok"},
    {"id": "1", "position": "Senior Software Engineer", "company": "Stripe",
     "url": "https://remoteok.com/jobs/1", "tags": ["python", "backend"], "description": ""},
    {"id": "2", "position": "Marketing Manager", "company": "Airbnb",
     "url": "https://remoteok.com/jobs/2", "tags": ["marketing"], "description": ""},
]


def _make_session_mock(resp_mock):
    """Build a properly wired aiohttp session mock."""
    get_cm = MagicMock()
    get_cm.__aenter__ = AsyncMock(return_value=resp_mock)
    get_cm.__aexit__ = AsyncMock(return_value=False)

    session = MagicMock()
    session.get = MagicMock(return_value=get_cm)

    session_cm = MagicMock()
    session_cm.__aenter__ = AsyncMock(return_value=session)
    session_cm.__aexit__ = AsyncMock(return_value=False)

    return session_cm


# ── Instantiation tests ──

class TestBoardInstantiation:
    @pytest.mark.parametrize("board_cls", ALL_BOARD_CLASSES, ids=lambda c: c.__name__)
    def test_instantiate_and_has_name(self, board_cls):
        board = board_cls()
        assert isinstance(board, JobBoard)
        assert board.name, f"{board_cls.__name__} has empty name"

    def test_unique_names(self):
        names = [cls().name for cls in ALL_BOARD_CLASSES]
        dupes = [n for n in names if names.count(n) > 1]
        assert len(names) == len(set(names)), f"Duplicate board names: {set(dupes)}"


class TestStubBoards:
    @pytest.mark.parametrize("board_cls", STUB_BOARDS, ids=lambda c: c.__name__)
    @pytest.mark.asyncio
    async def test_stub_returns_empty(self, board_cls):
        board = board_cls()
        listings = await board.fetch(["design"])
        assert listings == []


# ── Existing HTTP mock tests ──

@pytest.mark.asyncio
async def test_wwr_filters_by_keyword():
    board = WeWorkRemotelyBoard()
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.text = AsyncMock(return_value=WWR_RSS)

    with patch("job_search.boards.weworkremotely.aiohttp.ClientSession",
               return_value=_make_session_mock(mock_resp)):
        results = await board.fetch(["Senior Software Engineer"])

    assert len(results) == 1
    assert results[0].title == "Senior Software Engineer"
    assert results[0].company == "Stripe"


@pytest.mark.asyncio
async def test_remoteok_filters_by_keyword():
    board = RemoteOKBoard()
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=REMOTEOK_JSON)

    with patch("job_search.boards.remoteok.aiohttp.ClientSession",
               return_value=_make_session_mock(mock_resp)):
        results = await board.fetch(["Senior Software Engineer"])

    assert len(results) == 1
    assert results[0].company == "Stripe"



# ── Parse logic tests (no HTTP) ──

class TestRemotiveParse:
    def test_basic(self):
        board = RemotiveBoard()
        data = {"jobs": [{
            "url": "https://remotive.com/jobs/1",
            "title": "Product Designer",
            "company_name": "TestCo",
            "candidate_required_location": "Worldwide",
            "salary": "$100k",
            "description": "Great job",
            "tags": ["design"],
        }]}
        listings = board._parse(data, ["design"])
        assert len(listings) == 1
        assert listings[0].board == "remotive"
        assert listings[0].company == "TestCo"

    def test_empty(self):
        assert RemotiveBoard()._parse({}, ["design"]) == []

    def test_keyword_filter(self):
        data = {"jobs": [{
            "url": "https://remotive.com/jobs/1",
            "title": "Backend Engineer",
            "company_name": "X",
            "candidate_required_location": "",
            "salary": "",
            "description": "",
            "tags": [],
        }]}
        assert RemotiveBoard()._parse(data, ["design"]) == []


class TestHimalayasParse:
    def test_basic(self):
        board = HimalayasBoard()
        data = {"jobs": [{
            "title": "UX Designer",
            "companyName": "HCo",
            "url": "https://himalayas.app/jobs/ux-designer",
            "locationRestrictions": ["Worldwide"],
            "description": "Design stuff",
            "categories": ["design"],
        }]}
        listings = board._parse(data, ["design"])
        assert len(listings) == 1
        assert listings[0].title == "UX Designer"

    def test_slug_fallback(self):
        board = HimalayasBoard()
        data = {"jobs": [{
            "title": "Designer",
            "companyName": "Co",
            "url": "",
            "slug": "designer-at-co",
            "locationRestrictions": [],
            "description": "",
            "categories": ["design"],
        }]}
        listings = board._parse(data, ["design"])
        assert len(listings) == 1
        assert "himalayas.app/jobs/designer-at-co" in listings[0].url

    def test_empty(self):
        assert HimalayasBoard()._parse({}, ["design"]) == []


class TestYCombinatorParse:
    def test_basic(self):
        board = YCombinatorBoard()
        data = {"results": [{"hits": [{
            "title": "Design Lead",
            "companyName": "YC Startup",
            "slug": "design-lead-abc",
            "companySlug": "yc-startup",
            "location": "Remote",
            "salaryMin": 120000,
            "salaryMax": 180000,
            "description": "Lead design.",
        }]}]}
        listings = board._parse(data, ["design"])
        assert len(listings) == 1
        assert "workatastartup.com" in listings[0].url
        assert "$120,000" in listings[0].compensation

    def test_empty(self):
        assert YCombinatorBoard()._parse({}, ["design"]) == []
        assert YCombinatorBoard()._parse({"results": []}, ["design"]) == []

    def test_skips_no_slug(self):
        data = {"results": [{"hits": [{"title": "X", "companyName": "Y", "slug": ""}]}]}
        assert YCombinatorBoard()._parse(data, ["design"]) == []


class TestDiceParse:
    def test_basic(self):
        board = DiceBoard()
        data = {"data": [{
            "title": "UX Designer",
            "companyName": "Dice Corp",
            "detailsPageUrl": "https://dice.com/jobs/ux-designer",
            "jobLocation": {"displayName": "Remote"},
            "salary": "$90k",
        }]}
        listings = board._parse(data, ["design", "ux"])
        assert len(listings) == 1
        assert listings[0].company == "Dice Corp"

    def test_empty(self):
        assert DiceBoard()._parse({}, ["design"]) == []
        assert DiceBoard()._parse({"data": []}, ["design"]) == []

    def test_keyword_filter(self):
        data = {"data": [{
            "title": "Backend Engineer",
            "companyName": "X",
            "detailsPageUrl": "https://dice.com/jobs/1",
        }]}
        assert DiceBoard()._parse(data, ["design"]) == []


# ── Dribbble parse tests ──

DRIBBBLE_HTML = """
<ol class="job-board-job-list">
<li class="job-list-item  job-list-item--boosted job-list-item--featured">
  <a class="job-link" rel="nofollow" href="/jobs/299285-Remote-Senior-Product-Designer?source=index"></a>
  <div class="job-details-container">
    <div class="job-title-company-container">
      <div class="job-role display-flex align-center">
        <span class="job-board-job-company">Artisan</span>
      </div>
      <h4 class="job-title job-board-job-title">Remote Senior Product Designer</h4>
    </div>
  </div>
  <div class="job-additional-details-container">
    <div class="job-details">
      <span class="location">Remote</span>
    </div>
  </div>
</li>
<li class="job-list-item">
  <a class="job-link" href="/jobs/302948-Senior-UI-UX-Engineer?source=index"></a>
  <div class="job-details-container">
    <div class="job-title-company-container">
      <div class="job-role display-flex align-center">
        <span class="job-board-job-company">TechCo</span>
      </div>
      <h4 class="job-title job-board-job-title">Senior UI/UX Engineer</h4>
    </div>
  </div>
  <div class="job-additional-details-container">
    <div class="job-details">
      <span class="location">New York, NY</span>
    </div>
  </div>
</li>
</ol>
"""


class TestDribbbleParse:
    def test_basic(self):
        board = DribbbleBoard()
        listings = board._parse_html(DRIBBBLE_HTML)
        assert len(listings) == 2
        assert listings[0].title == "Remote Senior Product Designer"
        assert listings[0].company == "Artisan"
        assert listings[0].location == "Remote"
        assert "dribbble.com/jobs/299285" in listings[0].url

    def test_keyword_filter(self):
        board = DribbbleBoard()
        listings = board._parse_html(DRIBBBLE_HTML)
        from job_search.boards.dribbble import _keyword_filter
        filtered = _keyword_filter(listings, ["marketing"])
        assert len(filtered) == 0  # neither title nor company matches

    def test_empty(self):
        board = DribbbleBoard()
        assert board._parse_html("<html></html>") == []


# ── Behance parse tests ──

BEHANCE_HTML = """
<ul class="JobCardGrid-jobCardList-utJ" role="feed">
<li class="" role="article"><div class="JobCard-jobCard-mzZ">
  <a href="/joblist/343735/Brand-Designer-(Motion-Graphics)" class="JobCard-jobCardLink-Ywm" aria-label="Brand Designer (Motion Graphics)"></a>
  <div class="JobCard-companyHeader-ufg">
    <span class="JobCard-companyName-QXT"><p class="JobCard-company-GQS">Patreon</p></span>
    <p class="JobCard-jobLocation-sjd">New York, NY, USA</p>
  </div>
  <h3 class="JobCard-jobTitle-LS4">Brand Designer (Motion Graphics)</h3>
  <p class="JobCard-jobDescription-SYp">We are looking for a creative designer.</p>
</div></li>
<li class="" role="article"><div class="JobCard-jobCard-mzZ">
  <a href="/joblist/339863/Associate-Eyewear-Designer" class="JobCard-jobCardLink-Ywm" aria-label="Associate Eyewear Designer"></a>
  <div class="JobCard-companyHeader-ufg">
    <span class="JobCard-companyName-QXT"><p class="JobCard-company-GQS">Krewe</p></span>
    <p class="JobCard-jobLocation-sjd">New Orleans, LA, USA</p>
  </div>
  <h3 class="JobCard-jobTitle-LS4">Associate Eyewear Designer</h3>
  <p class="JobCard-jobDescription-SYp">Join our design team.</p>
</div></li>
</ul>
"""


class TestBehanceParse:
    def test_basic(self):
        board = BehanceBoard()
        listings = board._parse_html(BEHANCE_HTML)
        assert len(listings) == 2
        assert listings[0].title == "Brand Designer (Motion Graphics)"
        assert listings[0].company == "Patreon"
        assert listings[0].location == "New York, NY, USA"
        assert "/joblist/343735/" in listings[0].url

    def test_description(self):
        board = BehanceBoard()
        listings = board._parse_html(BEHANCE_HTML)
        assert "creative designer" in listings[0].description

    def test_empty(self):
        board = BehanceBoard()
        assert board._parse_html("<html></html>") == []


# ── Coroflot parse tests ──

COROFLOT_HTML = """
<ul class="listing_jobs" id="job_listings">
<li data-c-asset-id="672693" class="">
    <a href="https://www.coroflot.com/design-jobs/Senior-Graphic-Designer-Weigel-672693" data-job-id="672693">
        <div class="inner_full_wrap">
            <div class="details">
                <div class="company_name">Weigel Broadcasting Co</div>
                <div class="job_title">Senior Graphic Designer</div>
            </div>
            <span class="loc">Chicago, IL</span>
        </div>
    </a>
</li>
<li data-c-asset-id="672672" class="">
    <a href="https://www.coroflot.com/design-jobs/Business-Manager-Laurino-672672" data-job-id="672672">
        <div class="inner_full_wrap">
            <div class="details">
                <div class="company_name">Laurino Design</div>
                <div class="job_title">Business Manager</div>
            </div>
            <span class="loc">New York, NY</span>
        </div>
    </a>
</li>
</ul>
"""


class TestCoroflotParse:
    def test_basic(self):
        board = CoroflotBoard()
        listings = board._parse_html(COROFLOT_HTML)
        assert len(listings) == 2
        assert listings[0].title == "Senior Graphic Designer"
        assert listings[0].company == "Weigel Broadcasting Co"
        assert listings[0].location == "Chicago, IL"
        assert "672693" in listings[0].url

    def test_keyword_filter(self):
        board = CoroflotBoard()
        listings = board._parse_html(COROFLOT_HTML)
        from job_search.boards.coroflot import _keyword_filter
        filtered = _keyword_filter(listings, ["designer"])
        assert len(filtered) == 1
        assert filtered[0].title == "Senior Graphic Designer"

    def test_empty(self):
        board = CoroflotBoard()
        assert board._parse_html("<html></html>") == []


# ── BuiltIn parse tests ──

BUILTIN_HTML = """
<div id="job-card-8698187" data-id="job-card" class="job-bounded-responsive">
  <div id="main" class="row">
    <div class="left-side-tile-item-2">
      <a href="/company/webflow" data-id="company-title" data-builtin-track-job-id="8698187" class="font-barlow">
        <span>Webflow</span>
      </a>
    </div>
    <div class="left-side-tile-item-3">
      <h2 class="font-barlow">
        <a href="/job/staff-product-designer/8698187" target="_blank" data-id="job-card-title" class="card-alias-after-overlay">Staff Product Designer</a>
      </h2>
    </div>
    <div class="d-flex align-items-start gap-sm">
      <div class="d-flex justify-content-center align-items-center h-lg min-w-md">
        <i class="fa-regular fa-house-building fs-xs text-pretty-blue"></i>
      </div>
      <span class="font-barlow text-gray-04">Remote</span>
    </div>
    <div class="d-flex align-items-start gap-sm">
      <div class="d-flex justify-content-center align-items-center h-lg min-w-md">
        <i class="fa-regular fa-sack-dollar fs-xs text-pretty-blue"></i>
      </div>
      <span class="font-barlow text-gray-04">164K-238K Annually</span>
    </div>
  </div>
  <div class="fs-sm fw-regular mb-md text-gray-04">The Staff Product Designer at Webflow will define and launch new products.</div>
</div>
"""


class TestBuiltInParse:
    def test_basic(self):
        board = BuiltInBoard()
        listings = board._parse(BUILTIN_HTML, ["design"])
        assert len(listings) == 1
        assert listings[0].title == "Staff Product Designer"
        assert listings[0].company == "Webflow"
        assert listings[0].compensation == "164K-238K Annually"
        assert listings[0].remote == "yes"
        assert "builtin.com/job/staff-product-designer" in listings[0].url

    def test_description(self):
        board = BuiltInBoard()
        listings = board._parse(BUILTIN_HTML, [])
        assert "Webflow" in listings[0].description

    def test_keyword_filter(self):
        board = BuiltInBoard()
        listings = board._parse(BUILTIN_HTML, ["backend"])
        assert len(listings) == 0

    def test_empty(self):
        board = BuiltInBoard()
        assert board._parse("<html></html>", ["design"]) == []


# ── Nodesk parse tests ──

NODESK_RSS = """<?xml version="1.0" encoding="utf-8" standalone="yes"?>
<rss version="2.0">
  <channel>
    <title>Remote Design Jobs on NoDesk</title>
    <item>
      <title>Staff Product Designer at Dropbox</title>
      <link>https://nodesk.co/remote-jobs/dropbox-staff-product-designer/</link>
      <description>Dropbox is hiring a remote Staff Product Designer.</description>
      <pubDate>Fri, 06 Mar 2026 08:00:00 +0200</pubDate>
    </item>
    <item>
      <title>Email Marketing Designer at Eight Sleep</title>
      <link>https://nodesk.co/remote-jobs/eight-sleep-email-marketing-designer/</link>
      <description>Eight Sleep is hiring a remote Email Marketing Designer.</description>
      <pubDate>Sat, 07 Mar 2026 08:00:00 +0200</pubDate>
    </item>
    <item>
      <title>Backend Engineer at SomeCo</title>
      <link>https://nodesk.co/remote-jobs/someco-backend-engineer/</link>
      <description>SomeCo is hiring a remote Backend Engineer.</description>
      <pubDate>Sat, 07 Mar 2026 08:00:00 +0200</pubDate>
    </item>
  </channel>
</rss>"""


class TestNodeskParse:
    def test_basic(self):
        board = NodeskBoard()
        listings = board._parse(NODESK_RSS, ["designer"])
        assert len(listings) == 2
        assert listings[0].title == "Staff Product Designer"
        assert listings[0].company == "Dropbox"
        assert listings[0].remote == "yes"
        assert "nodesk.co" in listings[0].url

    def test_title_at_company_parsing(self):
        board = NodeskBoard()
        listings = board._parse(NODESK_RSS, [])
        assert listings[0].company == "Dropbox"
        assert listings[1].company == "Eight Sleep"

    def test_keyword_filter(self):
        board = NodeskBoard()
        listings = board._parse(NODESK_RSS, ["backend"])
        assert len(listings) == 1
        assert listings[0].company == "SomeCo"

    def test_empty(self):
        board = NodeskBoard()
        assert board._parse("<rss><channel></channel></rss>", ["design"]) == []

    def test_invalid_xml(self):
        board = NodeskBoard()
        assert board._parse("not valid xml <><>", ["design"]) == []
