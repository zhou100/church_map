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
