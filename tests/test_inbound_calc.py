"""inbound/calc.js under node: the page's numbers must match a hand calculation."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parent.parent / "inbound" / "calc.js"


def run(expr: str):
    code = f"const C=require({json.dumps(str(JS))}); console.log(JSON.stringify({expr}))"
    return json.loads(subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True).stdout)


pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node not installed")


def test_hand_calculation_case_1():
    # 1000 meals x 22 days; 1 plate, 1 cup, 1 fork per meal
    r = run("C.compute({meals:1000,days:22,counts:{plate:1,cup:1,cut:1,box:0}})")
    assert r["units"] == 66000
    assert r["rs"] == 22000 * 3 + 22000 * 1.5 + 22000 * 1       # 121,000
    assert round(r["bins"], 2) == round((22000 * .25 + 22000 * .2 + 22000 * .02) / 120, 2)


def test_hand_calculation_case_2_and_edited_prices():
    r = run("C.compute({meals:2000,days:26,counts:{plate:2,cup:1,cut:0,box:1}})")
    assert r["units"] == 208000 and r["rs"] == 104000 * 3 + 52000 * 1.5 + 52000 * 8     # 806,000
    r = run("C.compute({meals:1000,days:20,counts:{plate:1},costs:{plate:5}})")           # visitor edits the plate price
    assert r["rs"] == 20000 * 5


def test_bad_input_is_safe_and_shares_sum_to_one():
    r = run("C.compute({meals:-5,days:'x',counts:{plate:'a'}})")
    assert r["units"] == 0 and r["rs"] == 0
    s = run("C.shares(C.compute({meals:1000,days:22,counts:{plate:1,cup:1,cut:1,box:1}}),'rs')")
    assert abs(sum(p["frac"] for p in s) - 1) < 1e-9
    assert run("C.shares(C.compute({meals:0,days:22,counts:{}}),'units')")[0]["frac"] == 0       # no divide-by-zero


def test_indian_money_wording_and_routing():
    assert run("[C.inr(45000),C.inr(190000),C.inr(23000000)]") == ["Rs 45,000", "Rs 1.9 lakh", "Rs 2.3 crore"]
    assert run("[C.queueFor('corporate'),C.queueFor('fitout'),C.queueFor('caterer'),C.queueFor('institution')]") == ["warewashing", "kitchen design", "partner", "warewashing"]
