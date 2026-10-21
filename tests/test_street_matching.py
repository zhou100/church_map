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


# --- Review of 91be6af, issue 1: a number word is read as part of its whole phrase ----

@pytest.mark.parametrize("excerpt,street,ok", [
    ("Twenty-One Main Street, Oakland", "1 Main Street", False),
    ("Twenty One Main Street", "1 Main Street", False),
    ("Twenty-One Main Street, Oakland", "21 Main Street", True),
    ("One Hundred Five Elm Street", "105 Elm St", True),
    ("One Hundred Five Elm Street", "5 Elm St", False),
    ("One Notre Dame Avenue, San Jose", "1 Notre Dame Avenue", True),
])
def test_number_word_phrases(excerpt, street, ok):
    assert excerpt_supports_street(excerpt, street) is ok


# --- Review of 91be6af, issue 2: activity and language are attributed separately -------

def test_language_after_the_time_is_not_dropped_when_the_activity_precedes_it():
    page = "Sunday Mass 10 AM (Spanish); Sunday Mass 11 AM (English)"
    assert not excerpt_supports_service(page, "Sunday English Mass 10 AM")
    assert excerpt_supports_service(page, "Sunday Spanish Mass 10 AM")
    assert excerpt_supports_service(page, "Sunday English Mass 11 AM")
    assert excerpt_supports_service("Sunday 10 AM Mass in Spanish", "Sunday Spanish Mass 10 AM")


# Review of 69293de: a language the record states must be stated by the excerpt; a
# missing language in the excerpt is not a wildcard.
def test_record_language_must_be_stated_for_that_time():
    page = "Sunday Mass 10 AM; Sunday Mass 11 AM (Spanish)"
    assert not excerpt_supports_service(page, "Sunday English Mass 10 AM")
    assert excerpt_supports_service(page, "Sunday Mass 10 AM")             # no language claimed
    assert excerpt_supports_service(page, "Sunday Spanish Mass 11 AM")


def test_bare_times_continue_the_labelled_list_before_them():
    page = "Spanish Masses: Sunday 8:00 AM, 10:00 AM, 12:00 PM"
    assert excerpt_supports_service(page, "Sunday 12:00 PM Spanish Mass")
    assert not excerpt_supports_service(page, "Sunday 12:00 PM English Mass")
    # A fragment with its own labels doesn't inherit.
    assert not excerpt_supports_service("Sunday Mass 10 AM (Spanish); Sunday Mass 11 AM (English)",
                                        "Sunday Spanish Mass 11 AM")


@pytest.mark.parametrize("page,record,ok", [
    # One unlabelled time at the start doesn't flip a label-first clause ...
    ("English Worship Sunday 9:00am Weekly Services Sunday 10:00am Cantonese Sunday Worship 11:20am "
     "Mandarin Sunday Worship 10:00am", "Cantonese Sunday Worship 11:20am; Mandarin Sunday Worship 10:00am", True),
    # ... but a true tie is ambiguous, and an ambiguous layout withholds rather than guesses.
    ("Weekly Services Sunday 10:00am – 11:10am Cantonese Sunday Worship 11:20am – 12:40pm "
     "Mandarin Sunday Worship 10:00am – 11:10am", "Cantonese Sunday Worship 11:20am; Mandarin Sunday Worship 10:00am", False),
    ("Sunday Service 9:30 AM … Sunday School 11:00 AM … Cantonese worship 11:00 AM",
     "Cantonese worship 11:00 AM", True),
    # Label-first lists continue their label within the clause ...
    ("Sunday Mass: Spanish: 8:00 a.m.- 1:00 p.m. – 7:00 p.m. English: 9:30 a.m.",
     "Sunday: 8:00 AM Spanish, 1:00PM Spanish, 7:00PM Spanish, 9:30 AM English", True),
    # ... and across separators as a heading.
    ("ENGLISH / Sundays / 11:15 AM /// SPANISH / Sundays / 9:00 AM", "ENGLISH — Sundays 11:15 AM; SPANISH — Sundays 9:00 AM", True),
    # A trailing label belongs only to its own time.
    ("Sunday: 12:00 PM, 4:00 PM (Vietnamese), and 7:00 PM", "Sunday 7:00 PM Vietnamese Mass", False),
    ("Sunday 8:00am & 9:45am (English) … 11:30am (Japanese)", "Sunday 8:00am & 9:45am (English); 11:30am (Japanese)", True),
    # A language the page doesn't state is not supported.
    ("Mass Times Saturday 5:15PM Sunday 10:00AM", "Sunday: 10 am (English)", False),
    ("Sunday Mass 10 AM (Spanish); Sunday Mass 11 AM (English)", "Sunday English Mass 10 AM", False),
])
def test_service_labels_in_mixed_layouts(page, record, ok):
    assert excerpt_supports_service(page, record) is ok


@pytest.mark.parametrize("page,record,ok", [
    # Time-first clause: each label belongs to the time before it, never spread to the rest.
    ("08:00 AM English Mass 09:30 AM Sung Mass 11:30 AM Latin Sung Mass", "08:00 AM English Mass", True),
    ("08:00 AM English Mass 09:30 AM Sung Mass 11:30 AM Latin Sung Mass", "Mass 8:00 AM (English)", False),
    ("08:00 AM English Mass 09:30 AM Sung Mass 11:30 AM Latin Sung Mass", "11:30 AM English Mass", False),
    # Either reading fits; an ambiguous label backs neither time (unless quoted word for word).
    ("Saturday 4pm English (Vigil) Sunday 8am", "Saturday 4pm (Vigil) English", False),
    ("Saturday 4pm English (Vigil) Sunday 8am", "Sunday 8am English Mass", False),
])
def test_time_first_labels_stay_with_their_own_time(page, record, ok):
    assert excerpt_supports_service(page, record) is ok


def test_a_range_end_is_not_a_service_of_its_own():
    page = "Cantonese Sunday Worship 11:20am – 12:40pm; Mandarin Sunday Worship 10:00am – 11:10am"
    assert excerpt_supports_service(page, "Cantonese Sunday Worship: 11:20am – 12:40pm")
    assert not excerpt_supports_service(page, "Mandarin Sunday Worship 11:10am")
    # Times hours apart joined by dashes are a list, not a range.
    assert excerpt_supports_service("Sunday Mass: Spanish: 8:00 a.m.- 1:00 p.m. – 7:00 p.m.", "Sunday 7:00 PM Spanish")


def test_a_schedule_quoted_word_for_word_is_supported_even_where_layout_is_ambiguous():
    page = "Mass Schedules Saturday 4pm English (Vigil) Sunday 8am, 10am - Spanish"
    assert excerpt_supports_service(page, "Saturday 4pm English (Vigil) Sunday 8am")
    assert not excerpt_supports_service(page, "Sunday 8am English")


def test_a_labelled_fragment_does_not_inherit_the_previous_label():
    page = "Sunday Spanish Mass: 10:30 AM; Catechesis: 9:30 AM"
    assert not excerpt_supports_service(page, "Sunday 9:30 AM Spanish")
    assert excerpt_supports_service("Saturday 5:00 PM (Vigil English) … Sunday 8:00 AM (Portuguese)",
                                    "Saturday 5:00 PM English Vigil")
