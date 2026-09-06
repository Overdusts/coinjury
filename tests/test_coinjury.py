"""Offline unit tests for coinjury. No network. Run: python -m unittest -v"""
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import coinjury as cj  # noqa: E402

SAMPLE = json.loads((Path(cj.__file__).parent / "sample_data.json").read_text("utf-8"))
GIGA = next(t for t in SAMPLE if t["symbol"] == "GIGA")   # clean blue-chip-ish
RUGME = next(t for t in SAMPLE if t["symbol"] == "RUGME")  # thin fresh landmine


class VerdictBands(unittest.TestCase):
    def test_thresholds(self):
        self.assertEqual(cj.verdict_band(0)[0], "WATCH")
        self.assertEqual(cj.verdict_band(39)[0], "WATCH")
        self.assertEqual(cj.verdict_band(40)[0], "COINFLIP")
        self.assertEqual(cj.verdict_band(69)[0], "COINFLIP")
        self.assertEqual(cj.verdict_band(70)[0], "AVOID")
        self.assertEqual(cj.verdict_band(100)[0], "AVOID")


class Heuristic(unittest.TestCase):
    def test_clean_token_is_low_risk(self):
        risk, band, _ = cj.assess(GIGA)
        self.assertLess(risk, 40)
        self.assertEqual(band, "WATCH")

    def test_landmine_is_high_risk(self):
        risk, band, _ = cj.assess(RUGME)
        self.assertGreaterEqual(risk, 70)
        self.assertEqual(band, "AVOID")

    def test_score_is_clamped(self):
        self.assertEqual(cj.score_of([(80, "a"), (80, "b")]), 100)
        self.assertEqual(cj.score_of([]), 0)


class CriticalGates(unittest.TestCase):
    """Any critical gate must floor a clean token at AVOID."""
    def test_active_mint_authority_gates(self):
        info = {"src": ["rpc"], "mintAuth": "Aa11deadbeef", "freezeAuth": None}
        risk, band, flags = cj.assess(GIGA, info)
        self.assertGreaterEqual(risk, 75)
        self.assertEqual(band, "AVOID")
        self.assertTrue(any("mint authority" in f for f in flags))

    def test_freeze_authority_gates(self):
        info = {"src": ["rpc"], "mintAuth": None, "freezeAuth": "Bb22"}
        self.assertEqual(cj.assess(GIGA, info)[1], "AVOID")

    def test_rugged_gates(self):
        info = {"src": ["rugcheck"], "rugged": True}
        self.assertEqual(cj.assess(GIGA, info)[1], "AVOID")

    def test_high_transfer_tax_gates(self):
        info = {"src": ["rugcheck"], "transferFeePct": 25}
        self.assertEqual(cj.assess(GIGA, info)[1], "AVOID")

    def test_honeypot_no_sell_route_penalized(self):
        info = {"src": ["jupiter"], "sellable": False}
        risk, _, flags = cj.assess(GIGA, info)
        self.assertTrue(any("honeypot" in f for f in flags))
        self.assertGreater(risk, cj.assess(GIGA)[0])


class OnchainPenalties(unittest.TestCase):
    def test_low_lp_lock_adds_penalty(self):
        base = cj.assess(GIGA)[0]
        info = {"src": ["rugcheck"], "lpLockedPct": 10}
        self.assertGreater(cj.assess(GIGA, info)[0], base)

    def test_renounced_authorities_do_not_gate(self):
        info = {"src": ["rpc", "rugcheck"], "mintAuth": None,
                "freezeAuth": None, "rugged": False, "lpLockedPct": 100}
        self.assertEqual(cj.assess(GIGA, info)[1], "WATCH")


class Degradation(unittest.TestCase):
    def test_enrich_none_mint(self):
        self.assertIsNone(cj.enrich(""))
        self.assertIsNone(cj.enrich(None))

    def test_assess_without_info_is_heuristic_only(self):
        self.assertEqual(cj.assess(GIGA, None), cj.assess(GIGA))


class ChallengeRanking(unittest.TestCase):
    def test_rank_handles_equal_risk_ties(self):
        # two distinct tokens with identical risk must not crash the sort
        a, b = dict(GIGA, mint="AAA"), dict(GIGA, mint="BBB")
        graded = {"AAA": 30, "BBB": 30}
        out = cj.rank_by_risk([a, b], graded)
        self.assertEqual(len(out), 2)

    def test_rank_orders_safest_first(self):
        a, b = dict(GIGA, mint="AAA"), dict(GIGA, mint="BBB")
        graded = {"AAA": 80, "BBB": 10}
        self.assertEqual([t["mint"] for t in cj.rank_by_risk([a, b], graded)],
                         ["BBB", "AAA"])


class DemoPipelineOffline(unittest.TestCase):
    """The whole scan pipeline must run offline in demo mode and emit valid JSON."""
    def test_demo_scan_json(self):
        args = cj.build_parser().parse_args(
            ["scan", "--demo", "--min-liq", "0", "--json"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            cj.cmd_scan(args)
        data = json.loads(buf.getvalue())
        self.assertEqual(len(data), len(SAMPLE))
        self.assertTrue(all("verdict" in r and "risk" in r for r in data))
        # safest-first ordering
        risks = [r["risk"] for r in data]
        self.assertEqual(risks, sorted(risks))


if __name__ == "__main__":
    unittest.main(verbosity=2)
