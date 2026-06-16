from datetime import datetime
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import report_pipeline


def test_timeliness_windows_by_type():
    now = datetime(2026, 6, 11, 12, 0, 0)

    assert not report_pipeline.check_timeliness({"date": "2026-06-03"}, "news", now=now)[0]
    assert report_pipeline.check_timeliness({"date": "2026-05-29"}, "research", now=now)[0]
    assert not report_pipeline.check_timeliness({"date": "2026-05-27"}, "research", now=now)[0]
    assert report_pipeline.check_timeliness({"date": "2026-05-13"}, "policy", now=now)[0]
    assert not report_pipeline.check_timeliness({"date": "2026-05-11"}, "policy", now=now)[0]
    assert report_pipeline.check_timeliness({"date": "2026-06-11"}, "events", now=now)[0]
    assert not report_pipeline.check_timeliness({"date": "2026-06-10"}, "events", now=now)[0]
    assert not report_pipeline.check_timeliness({"date": "2026-09-11"}, "events", now=now)[0]
    assert not report_pipeline.check_timeliness({"date": "recently"}, "news", now=now)[0]
