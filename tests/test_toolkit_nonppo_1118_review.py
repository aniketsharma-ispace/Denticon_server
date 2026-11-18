"""Toolkit extension, 11/18 report: a Non-participating crawl refused a plan
whose out-of-network bucket the API names "Non-PPO Dentist".

Medicare Advantage PPO plans (Delta Dental of Michigan) return
memberbenefits/search with networks
    [{name: "PPO Dentist"}, {name: "Premier Dentist"},
     {name: "Non-PPO Dentist", alternateName: "Nonparticipating Dentist"}]
and every benefit bucket lists "Non-PPO Dentist". The faxback PDF calls the
same column "Nonparticipating Dentist". content_DD_Toolkit.js compared names
exactly, so the crawl stopped with "This plan has no Nonparticipating Dentist
network (it offers PPO Dentist, Premier Dentist, Non-PPO Dentist)".

The network helpers live inside the content script's IIFE, so this test lifts
their declarations out of the file and runs them in Node.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "Extension" / "content_DD_Toolkit.js"
NODE = shutil.which("node")

FUNCTIONS = ["cleanText", "toArray", "safeStringify", "uniqueStrings", "networkNameVariants",
             "useSelectedNetwork", "isSelectedNetworkName", "planNetworkNames",
             "isSelectedNetworkBucket"]


def _declaration(source, name):
    match = re.search(rf"^    (?:async )?function {name}\(.*?^    }}$", source, re.M | re.S)
    assert match, f"function {name} not found in {SCRIPT.name}"
    return match.group(0)


def _harness():
    source = SCRIPT.read_text(encoding="utf-8")
    choices = re.search(r"^    const NETWORK_CHOICES = .*?^    \]\);$", source, re.M | re.S)
    assert choices, "NETWORK_CHOICES not found"
    parts = [choices.group(0), "    let selectedNetwork = null;"]
    parts += [_declaration(source, name) for name in FUNCTIONS]
    return "\n".join(parts)


def run_node(body):
    if not NODE:
        pytest.skip("node is not installed")
    program = "(() => {\n" + _harness() + "\n" + body + "\n})();"
    out = subprocess.run([NODE, "-e", program], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


# Shape of the 11/18 memberbenefits/search response (network names only).
BENEFITS = {
    "networks": [
        {"name": "PPO Dentist"},
        {"name": "Premier Dentist"},
        {"name": "Non-PPO Dentist", "alternateName": "Nonparticipating Dentist"},
    ],
    "networkBenefits": [
        {"networks": ["PPO Dentist"]},
        {"networks": ["Premier Dentist", "Non-PPO Dentist"]},
    ],
    "maximumsAndDeductions": [
        {"networks": ["PPO Dentist", "Premier Dentist", "Non-PPO Dentist"]},
    ],
}


def check(network):
    return run_node(f"""
        const benefits = {json.dumps(BENEFITS)};
        useSelectedNetwork({json.dumps(network)});
        const offered = planNetworkNames(benefits);
        console.log(JSON.stringify({{
            selected: selectedNetwork,
            offered,
            plan_offers_it: offered.some(isSelectedNetworkName),
            object_form: isSelectedNetworkName(benefits.networks[2]),
            buckets: benefits.networkBenefits.map(isSelectedNetworkBucket),
            maximums: benefits.maximumsAndDeductions.map(isSelectedNetworkBucket),
            names: Object.fromEntries(["PPO Dentist", "Premier Dentist", "Non-PPO Dentist",
                "Nonparticipating Dentist", "Non-participating Dentist"]
                .map(name => [name, isSelectedNetworkName(name)])),
        }}));
    """)


def test_nonparticipating_crawl_accepts_non_ppo_plan():
    got = check("oon")
    assert got["selected"] == "Nonparticipating Dentist"
    assert got["offered"] == ["PPO Dentist", "Premier Dentist", "Non-PPO Dentist"]
    assert got["plan_offers_it"] is True


def test_nonparticipating_reads_the_non_ppo_buckets():
    got = check("oon")
    assert got["buckets"] == [False, True]
    assert got["maximums"] == [True]
    assert got["object_form"] is True


def test_nonparticipating_names_both_spellings():
    names = check("oon")["names"]
    assert names == {"PPO Dentist": False, "Premier Dentist": False, "Non-PPO Dentist": True,
                     "Nonparticipating Dentist": True, "Non-participating Dentist": True}


def test_ppo_does_not_match_non_ppo():
    got = check("ppo")
    assert got["names"]["PPO Dentist"] is True
    assert got["names"]["Non-PPO Dentist"] is False
    assert got["buckets"] == [True, False]
    assert got["object_form"] is False


def test_premier_unchanged():
    got = check("premier")
    assert got["names"] == {"PPO Dentist": False, "Premier Dentist": True, "Non-PPO Dentist": False,
                            "Nonparticipating Dentist": False, "Non-participating Dentist": False}
    assert got["buckets"] == [False, True]


# ── Server side: "OON Benefits" from the plan's network list (Smile and Star) ──
# A plan whose network list names a non-participating network pays out of
# network (Smile 11/10, Star 11/09). "Non-PPO Dentist" is that network on
# Medicare Advantage PPO plans, so it counts too.

from smile_partners.portals import delta_toolkit as smile_toolkit  # noqa: E402
from star_dental.portals import delta_toolkit as star_toolkit  # noqa: E402

PORTALS = pytest.mark.parametrize("portal", [smile_toolkit, star_toolkit], ids=["smile", "star"])


def _oon_stated(portal, networks, key="offered_by_plan"):
    out = portal._normalize_delta_toolkit_portal({"networks": {key: networks}})
    return out["_toolkit_meta"]["oon_stated"]


@PORTALS
@pytest.mark.parametrize("key", ["offered_by_plan", "available_in_output"])
def test_non_ppo_network_states_oon_benefits(portal, key):
    assert _oon_stated(portal, ["PPO Dentist", "Premier Dentist", "Non-PPO Dentist"], key) is True


@PORTALS
@pytest.mark.parametrize("name", ["Nonparticipating Dentist", "MN Non-NPF Non Par Dentist",
                                  "Non-participating Dentist", "non ppo dentist"])
def test_other_non_participating_names_still_state_oon(portal, name):
    assert _oon_stated(portal, ["PPO Dentist", name]) is True


@PORTALS
@pytest.mark.parametrize("networks", [["PPO Dentist", "Premier Dentist"], ["PPO Dentist"],
                                      ["MN Non-NPF Dentist"]])
def test_in_network_lists_state_no_oon(portal, networks):
    assert _oon_stated(portal, networks) is False
