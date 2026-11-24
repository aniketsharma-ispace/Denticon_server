"""Toolkit extension, 11/24 report: a Non-participating crawl refused a plan
whose out-of-network bucket the API names "MN Non-NPF Non Par Dentist".

memberbenefits/search returned networks
    [{name: "PPO Dentist"}, {name: "Premier Dentist"},
     {name: "MN Non-NPF Non Par Dentist", alternateName: "Nonparticipating Dentist"}]
and every benefit bucket listed "MN Non-NPF Non Par Dentist". The crawl stopped
with "This plan has no Nonparticipating Dentist network (it offers PPO Dentist,
Premier Dentist, MN Non-NPF Non Par Dentist)". The 11/18 fix ("Non-PPO Dentist")
added one more alias; the out-of-network name differs from plan to plan, so from
extension 1.63 PPO and Premier are matched by their exact names and every other
network name is Non-participating.

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

FUNCTIONS = ["cleanText", "toArray", "safeStringify", "uniqueStrings", "networkChoiceForNames",
             "useSelectedNetwork", "isSelectedNetworkName", "planNetworkNames",
             "isSelectedNetworkBucket", "selectedNetworkTabNames"]


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


OON = "MN Non-NPF Non Par Dentist"

# Shape of the 11/24 memberbenefits/search response (network names only).
BENEFITS = {
    "networks": [
        {"alternateName": None, "name": "PPO Dentist"},
        {"alternateName": None, "name": "Premier Dentist"},
        {"alternateName": "Nonparticipating Dentist", "name": OON},
    ],
    "networkBenefits": [
        {"networks": ["PPO Dentist", "Premier Dentist", OON]},
        {"networks": ["PPO Dentist"]},
        {"networks": ["Premier Dentist", OON]},
    ],
    "maximumsAndDeductions": [
        {"networks": ["PPO Dentist", "Premier Dentist", OON]},
    ],
}

NAMES = ["PPO Dentist", "Premier Dentist", OON, "Nonparticipating Dentist", "Non-PPO Dentist",
         "Non-participating Dentist", "WI Non-NPF Non Par Dentist", "ppo dentist", ""]


def check(network):
    return run_node(f"""
        const benefits = {json.dumps(BENEFITS)};
        useSelectedNetwork({json.dumps(network)});
        const offered = planNetworkNames(benefits);
        console.log(JSON.stringify({{
            selected: selectedNetwork,
            offered,
            plan_offers_it: offered.some(isSelectedNetworkName),
            objects: benefits.networks.map(isSelectedNetworkName),
            buckets: benefits.networkBenefits.map(isSelectedNetworkBucket),
            maximums: benefits.maximumsAndDeductions.map(isSelectedNetworkBucket),
            tabs: selectedNetworkTabNames(benefits),
            names: Object.fromEntries({json.dumps(NAMES)}.map(name => [name, isSelectedNetworkName(name)])),
        }}));
    """)


def test_nonparticipating_crawl_accepts_the_1124_plan():
    got = check("oon")
    assert got["selected"] == "Nonparticipating Dentist"
    assert got["offered"] == ["PPO Dentist", "Premier Dentist", OON]
    assert got["plan_offers_it"] is True


def test_nonparticipating_reads_the_state_named_buckets():
    got = check("oon")
    assert got["objects"] == [False, False, True]
    assert got["buckets"] == [True, False, True]
    assert got["maximums"] == [True]


def test_nonparticipating_is_every_name_but_ppo_and_premier():
    names = check("oon")["names"]
    assert names == {"PPO Dentist": False, "Premier Dentist": False, OON: True,
                     "Nonparticipating Dentist": True, "Non-PPO Dentist": True,
                     "Non-participating Dentist": True, "WI Non-NPF Non Par Dentist": True,
                     "ppo dentist": False, "": False}


def test_nonparticipating_tab_is_found_under_the_plans_own_name():
    tabs = check("oon")["tabs"]
    assert set(tabs) == {"nonparticipating dentist", OON.lower()}


def test_ppo_is_exact():
    got = check("ppo")
    assert got["objects"] == [True, False, False]
    assert got["buckets"] == [True, True, False]
    assert {k for k, v in got["names"].items() if v} == {"PPO Dentist", "ppo dentist"}
    assert got["tabs"] == ["ppo dentist"]


def test_premier_is_exact():
    got = check("premier")
    assert got["objects"] == [False, True, False]
    assert got["buckets"] == [True, False, True]
    assert {k for k, v in got["names"].items() if v} == {"Premier Dentist"}
    assert got["tabs"] == ["premier dentist"]
