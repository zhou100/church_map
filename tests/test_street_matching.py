"""Full-street address matching shared by the validator, repair tool and seeds (no network).

Review finding: matching only the house number and the first street word accepted
"107 San Mateo Avenue" as evidence for "107 San Pedro Road".
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "muse_handoff"))
from validate_returns import excerpt_supports_street, street_key  # noqa: E402


@pytest.mark.parametrize("excerpt,street", [
    ("Parish office: 107 San Mateo Avenue, San Bruno", "107 San Pedro Road"),   # same number + first word
    ("107 San Pedro Avenue, Colma", "107 San Pedro Road"),                      # same name, other suffix
    ("1107 San Pedro Road, Colma", "107 San Pedro Road"),                       # number inside a number
    ("107 W San Pedro Rd", "107 E San Pedro Rd"),                               # other direction
    ("600 42nd Avenue", "600 W 42nd Avenue"),                                   # direction missing
    ("1501 S. El Camino Real, Millbrae", "1501 N El Camino Real"),
    ("1860 Grant Road Los Altos", "1860 Grant Ave"),                            # seen in C-054 after re-sourcing
    ("5284 Monterey Highway, San Jose", "5284 Monterey Rd."),                   # seen in D-059 after re-sourcing
    ("1555 38th Avenue", "1555 39th Avenue"),
])
def test_different_street_is_not_evidence(excerpt, street):
    assert not excerpt_supports_street(excerpt, street)


@pytest.mark.parametrize("excerpt,street", [
    ("Holy Angels 107 San Pedro Road Colma, CA 94014", "107 San Pedro Rd"),
    ("900 Edgewater Blvd. Foster City", "900 Edgewater Boulevard"),
    ("600 West 42nd Ave, San Mateo", "600 W. 42nd Avenue"),
    ("ADDRESS 10455 BANDLEY DR STE 100 Cupertino", "10455 Bandley Dr Ste 100"),
    ("10455 BANDLEY DR, Cupertino", "10455 Bandley Dr Ste 100"),                # unit after the suffix is ignored
    ("Our location: 6210 Geary Boulevard, San Francisco", "6210 Geary Blvd"),
    ("1501 S. El Camino Real, San Mateo", "1501 S El Camino Real"),
    ("Visit us at 107 San Pedro, Colma", "107 San Pedro Road"),                 # suffix omitted, none substituted
    ("1555 39 Avenue San Francisco, CA 94122", "1555 39th Avenue"),             # ordinal written without suffix
    ("Address : 1971 Saint Lawrence Dr. Santa Clara", "1971 St. Lawrence Dr."), # St. = Saint in a name
])
def test_same_street_in_another_spelling_is_evidence(excerpt, street):
    assert excerpt_supports_street(excerpt, street)


def test_street_key_stops_at_the_suffix():
    assert street_key("10455 Bandley Dr Ste 100") == ("10455", ("bandley", "dr"))
    assert street_key("Corner of Alameda & Crystal Springs") is None


# --- Review of e9980b51, issue 2: service times must match day and time -----------

from validate_returns import excerpt_supports_service  # noqa: E402


@pytest.mark.parametrize("excerpt,verbatim", [
    ("Saturday Bible study 10 AM; Sunday worship 11 AM", "Sunday worship 10 AM"),   # time belongs to Saturday
    ("Sunday worship 11 AM", "Sunday worship 10 AM"),
    ("Saturday Mass 5:00 PM", "Sunday Mass 5:00 PM"),                               # same time, other day
    ("Sunday 9:00 AM", "Sunday 9:00 PM"),
    ("Sunday Bible study 10 AM; Sunday worship 11 AM", "Sunday worship 10 AM"),     # same day, other activity
    ("Sunday 10:00 AM Spanish Mass", "Sunday 10:00 AM English Mass"),               # other language
    ("Worship at 10 AM", "Sunday worship 10 AM"),                                   # day not stated
])
def test_service_excerpt_with_other_time_or_day_does_not_support(excerpt, verbatim):
    assert not excerpt_supports_service(excerpt, verbatim)


@pytest.mark.parametrize("excerpt,verbatim", [
    ("Join the Sunday Celebration / Every Sunday at 10 am Pacific", "Every Sunday at 10 am Pacific"),
    ("Sunday: 9:00 AM English, 11:00 AM English, 3:00 PM Vietnamese", "Sunday: 9:00 AM English, 11:00 AM English, 3:00 PM Vietnamese"),
    ("主日崇拜 10:00am (國語)", "主日崇拜 10:00 am"),
    ("Domingo 12:30 p.m. en Español", "Domingo 12:30 pm"),
    ("우리교회의 주일 예배시간은 주일 오전 11시 입니다.", "주일 예배 11:00 AM"),
    ("彌撒時間﹕ 第二,第四及第五個主日下午一時半", "主日 1:30 pm"),
    ("Saturday 5:00 PM Vigil; Sunday 8:00 AM, 10:00 AM", "Sunday 10:00 AM"),        # day carries over
])
def test_service_excerpt_with_same_days_and_times_supports(excerpt, verbatim):
    assert excerpt_supports_service(excerpt, verbatim)


def test_a_day_named_after_the_times_does_not_capture_them():
    page = "Mass Schedule: Saturday 5:00 PM Vigil; Sunday 8:00 AM, 10:00 AM and 12:00 PM (Spanish). Confessions Saturday 4:00 PM."
    assert excerpt_supports_service(page, "Sunday 8:00 AM, 10:00 AM and 12:00 PM (Spanish)")
    assert not excerpt_supports_service(page, "Saturday 10:00 AM")


def test_activity_comes_from_the_nearest_keyword_not_the_whole_clause():
    verbatim = "主日崇拜（粵語）：每週日上午 9:00；兒童主日學：每週日上午 9:00；英文崇拜：每月兩次主日上午 10:45–12:00"
    excerpt = " 主日崇拜（粵語）：每週日上午 9:00 兒童主日學：每週日上午 9:00 英文崇拜：每月兩次主日上午 10:45–12:00"
    assert excerpt_supports_service(excerpt, verbatim)
    assert excerpt_supports_service("9:40am 成人主日學 11:00am 國語主日崇拜", "11:00am 國語主日崇拜")
    assert not excerpt_supports_service("Sunday 10 AM Bible study 11 AM worship", "Sunday worship 10 AM")


def test_house_number_with_a_letter_suffix():
    assert excerpt_supports_street("592A Tennent Avenue / Pinole, California 94564", "592A Tennent Avenue")
    assert not excerpt_supports_street("592B Tennent Avenue, Pinole", "592A Tennent Avenue")
    assert not excerpt_supports_street("592 Tennent Avenue, Pinole", "592A Tennent Avenue")


def test_house_number_spelled_out():
    assert excerpt_supports_street("Parish office: One Notre Dame Avenue, San Jose", "1 Notre Dame Avenue")
    assert not excerpt_supports_street("Two Notre Dame Avenue", "1 Notre Dame Avenue")


def test_every_weekday_ends_the_previous_days_scope():
    v = "Domingo: 11am - 1pm (Servicio General); Jueves: 7pm - 8:30pm (Estudio Biblico)"
    assert excerpt_supports_service("Domingo: 11am - 1pm (Servicio General)", "Domingo: 11am - 1pm (Servicio General)")
    assert not excerpt_supports_service("Domingo: 7pm", "Jueves: 7pm")
    assert excerpt_supports_service("Dom 11:00 AM (General)", "Domingo 11:00 AM")
