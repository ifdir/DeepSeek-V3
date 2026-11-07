"""Stand 05: Gesamtkette Einwilligung mit ECHTEM Rust (kein Mock).

Kette je Abfrage:
  scene_state-Reader (Kandidat) -> body_contact_entries -> _in_window je Ereignis
  -> native_boundary (FFI ABI 2) -> kompilierte libmatrix_boundary_core
  -> Index-Rueckgabe -> Python-Plausibilisierung -> Projektion auf Fakt-IDs.

Gepruefte Ebene: alle drei Reader GEMEINSAM ueber dieselbe Ereigniskette,
schrittweise nach jedem Ereignis (Zeitleiste), plus Kreuz-Invarianten
zwischen den Readern und ein Differenzlauf gegen den aus dem Patch
rekonstruierten Original-V67-Reader (SHA-256 wird geprueft).

NICHT gepruefte Ebene (bewusst, kein Ersatz): V67-Writer, SQLite,
Neustart, Folgeturn, HTTP, Frontend, User-/Session-Isolation. Dafuer fehlt
in dieser Umgebung MATRIX10_V67_ABHAENGIGKEIT_20261031.zip.

`matrix_api.ids` wird durch einen Stub ersetzt, der bei JEDEM Aufruf
fehlschlaegt: Er beweist, dass die Consent-Reader keine IDs erzeugen.
Er ist keine Nachbildung der V67-Datei.
"""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "integration"
PATCH = ROOT / "patches" / "scene_state.py.patch"
V67_SCENE_STATE_SHA256 = "2d3c0dfa98981d77cd5b1b9e5b8c5f480b4ac437b78d3a82f14ad212101617fe"
AT = "2026-11-07T12:00"
EXPIRED = {"art": "zeit", "start": "2026-11-01T12:00", "end": "2026-11-01T13:00"}
CURRENT = {"art": "zeit", "start": "2026-11-07T11:00", "end": "2026-11-07T13:00"}


def _ids_stub() -> types.ModuleType:
    mod = types.ModuleType("ids")

    def uid(*_a, **_k):
        raise AssertionError("Consent-Reader darf keine ID erzeugen (ids.uid aufgerufen)")
    mod.uid = uid
    return mod


def _load_package(pkg: str, scene_state_file: Path, with_bridge: bool):
    package = types.ModuleType(pkg)
    package.__path__ = [str(scene_state_file.parent)]
    sys.modules[pkg] = package
    ids = _ids_stub()
    ids.__name__ = pkg + ".ids"
    sys.modules[pkg + ".ids"] = ids
    loaded = {}
    files = [("scene_state", scene_state_file)]
    if with_bridge:
        files.insert(0, ("native_boundary", SRC / "native_boundary.py"))
    for name, path in files:
        spec = importlib.util.spec_from_file_location(f"{pkg}.{name}", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"{pkg}.{name}"] = module
        spec.loader.exec_module(module)
        loaded[name] = module
    return loaded


_TMP = tempfile.TemporaryDirectory(prefix="matrix05_v67ref_")


def _reconstruct_original() -> Path:
    target = Path(_TMP.name) / "scene_state.py"
    shutil.copy2(SRC / "scene_state.py", target)
    run = subprocess.run(["patch", "-R", "-s", str(target), str(PATCH)], capture_output=True, text=True)
    if run.returncode:
        raise RuntimeError("Original-V67-Rekonstruktion fehlgeschlagen: " + run.stderr)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    if digest != V67_SCENE_STATE_SHA256:
        raise RuntimeError(f"Rekonstruiertes Original hat falschen Hash {digest}")
    return target


cand = _load_package("matrix_api", SRC / "scene_state.py", with_bridge=True)
bridge, sc = cand["native_boundary"], cand["scene_state"]
if not bridge.library_path().is_file():
    raise RuntimeError(f"BLOCKIERT: native Bibliothek fehlt unter {bridge.library_path()} "
                       "(tools/build_chain_05.py ausfuehren). Kein Skip, kein Pass.")
orig = _load_package("matrix_v67_ref", _reconstruct_original(), with_bridge=False)["scene_state"]


# ---------------------------------------------------------------- Fixtures
def ev(i, by, kind, scope, part=None, window=None, open_part=None):
    kk = {"scope": scope, "einschraenkung": part, "window": window, "beleg": f"beleg-{i}"}
    if open_part is not None:
        kk["einschraenkung"], kk["scope"] = open_part, "diese_tat"
    return {"id": f"f{i}", "kind": "lifecycle", "event_kind": kind, "actorId": by,
            "propositionId": "prop", "validated": True, "turn": i, "text": f"event {i}",
            "payload": {"koerperkontakt": kk}}


def scene(facts):
    prop = {"id": "prop", "kind": "koerperkontakt", "actorId": "alice", "targetId": "bob"}
    return {"facts": list(facts), "propositions": [prop], "time": {}, "sceneState": {}}, prop


def snapshot(module, facts, at=AT):
    s, p = scene(facts)
    st = module.body_contact_standing(s, p, at=at)
    perms = module.restricted_permissions_standing(s, p, at=at)
    refs = module.restricted_refusals_standing(s, p, at=at)
    return {
        "state": None if st is None else st["state"],
        "cause": None if st is None else st["causeFactId"],
        "ausnahmen": [] if st is None or "ausnahmen" not in st else
        [(x["causeFactId"], x["kind"]) for x in st["ausnahmen"]],
        "perms": [x["einschraenkung"] for x in perms],
        "refs": [x["einschraenkung"] for x in refs],
    }


def assert_cross_invariants(tc, snap, facts):
    """Reader muessen dieselbe Wahrheit spiegeln, nicht drei verschiedene."""
    for a in snap["perms"]:
        for b in snap["refs"]:
            tc.assertFalse(bridge.restriction_match(a, b, "same"),
                           f"Teil gleichzeitig erlaubt und abgelehnt: {a!r} / {b!r}")
    by = {f["id"]: f["actorId"] for f in facts}
    if snap["cause"] is not None:
        tc.assertEqual(by[snap["cause"]], "bob", "Zustand von fremdem Sprecher verursacht")
    for fid, _kind in snap["ausnahmen"]:
        tc.assertEqual(by[fid], "bob", "Ausnahme von fremdem Sprecher verursacht")
    if snap["state"] == "accepted":
        tc.assertEqual(snap["perms"], [], "breite Zustimmung + Einzelerlaubnis doppelt gefuehrt")
    if snap["state"] == "declined":
        excepted = [k for _f, k in snap["ausnahmen"] if k == "acceptance"]
        tc.assertEqual(len(excepted), len(snap["perms"]),
                       "Ausnahmen unter Ablehnung und Einzelerlaubnisse laufen auseinander")


# ------------------------------------------------- Zeitleiste (Gesamtkette)
TIMELINE = [
    # (Ereignis, erwarteter Gesamtzustand nach dem Ereignis)
    (ev(1, "bob", "refusal", "jede_beruehrung"),
     dict(state="declined", cause="f1", ausnahmen=[], perms=[], refs=[])),
    (ev(2, "alice", "acceptance", "jede_beruehrung"),            # fremder Sprecher
     dict(state="declined", cause="f1", ausnahmen=[], perms=[], refs=[])),
    (ev(3, "bob", "acceptance", "eingeschraenkt", "rechte Hand"),
     dict(state="declined", cause="f1", ausnahmen=[("f3", "acceptance")], perms=["rechte Hand"], refs=[])),
    (ev(4, "bob", "acceptance", "eingeschraenkt", "linke Hand", window=EXPIRED),  # abgelaufen
     dict(state="declined", cause="f1", ausnahmen=[("f3", "acceptance")], perms=["rechte Hand"], refs=[])),
    (ev(5, "bob", "refusal", "eingeschraenkt", "meine rechte Hand"),  # gleiche Stelle, andere Stimme
     dict(state="declined", cause="f1", ausnahmen=[], perms=[], refs=["meine rechte Hand"])),
    (ev(6, "bob", "acceptance", "jede_beruehrung", window=EXPIRED),   # abgelaufen
     dict(state="declined", cause="f1", ausnahmen=[], perms=[], refs=["meine rechte Hand"])),
    (ev(7, "", "acceptance", "jede_beruehrung"),                      # leerer Sprecher
     dict(state="declined", cause="f1", ausnahmen=[], perms=[], refs=["meine rechte Hand"])),
    (ev(8, "bob", "acceptance", "jede_beruehrung", window=CURRENT),   # gueltig
     dict(state="accepted", cause="f8", ausnahmen=[], perms=[], refs=[])),
    (ev(9, "bob", "refusal", "eingeschraenkt", "Schulter"),
     dict(state="accepted", cause="f8", ausnahmen=[("f9", "refusal")], perms=[], refs=["Schulter"])),
    (ev(10, "alice", "refusal", "eingeschraenkt", "Nacken"),          # fremd
     dict(state="accepted", cause="f8", ausnahmen=[("f9", "refusal")], perms=[], refs=["Schulter"])),
    (ev(11, "bob", "revoke", "diese_tat"),
     dict(state="revoked", cause="f11", ausnahmen=[], perms=[], refs=["Schulter"])),
    (ev(12, "alice", "acceptance", "eingeschraenkt", "Schulter"),     # fremd
     dict(state="revoked", cause="f11", ausnahmen=[], perms=[], refs=["Schulter"])),
    (ev(13, "alice", "acceptance", "jede_beruehrung"),                # fremd
     dict(state="revoked", cause="f11", ausnahmen=[], perms=[], refs=["Schulter"])),
    (ev(14, "bob", "acceptance", "eingeschraenkt", "Schulter", window=EXPIRED),  # abgelaufen
     dict(state="revoked", cause="f11", ausnahmen=[], perms=[], refs=["Schulter"])),
    (ev(15, "bob", "acceptance", "eingeschraenkt", "Schulter"),       # >6 Ereignisse, keine Trunkierung
     dict(state="revoked", cause="f11", ausnahmen=[], perms=["Schulter"], refs=[])),
]


class ConsentChainNativeTests(unittest.TestCase):
    def test_native_library_is_abi_2_and_really_loaded(self):
        self.assertEqual(bridge._load().matrix_boundary_abi_version(), 2)

    def test_timeline_all_readers_after_every_event(self):
        facts = []
        for event, expected in TIMELINE:
            facts.append(event)
            with self.subTest(after=event["id"]):
                snap = snapshot(sc, facts)
                self.assertEqual(snap, expected)
                assert_cross_invariants(self, snap, facts)
        # Append-only: Reader veraendern keine Fakten.
        self.assertEqual([f["id"] for f in facts], [f"f{i}" for i in range(1, 16)])

    def test_timeline_is_order_stable_for_shuffled_storage(self):
        """Reader ordnet nach (turn, index); Speicherreihenfolge darf Ergebnis nicht aendern."""
        facts = [e for e, _ in TIMELINE]
        self.assertEqual(snapshot(sc, list(reversed(facts))), TIMELINE[-1][1])

    def test_window_boundaries_inclusive_and_missing_time(self):
        facts = [ev(1, "bob", "refusal", "jede_beruehrung"),
                 ev(2, "bob", "acceptance", "jede_beruehrung", window=CURRENT)]
        self.assertEqual(snapshot(sc, facts, at="2026-11-07T13:00")["state"], "accepted")
        self.assertEqual(snapshot(sc, facts, at="2026-11-07T13:01")["state"], "declined")
        # ohne Zeitpunkt deckt ein zeitbegrenztes Ereignis nichts ab
        self.assertEqual(snapshot(sc, facts, at=None)["state"], "declined")

    def test_scene_window_other_place_inactive(self):
        win = {"art": "szene", "placeId": "kueche", "seitTurn": 1}
        facts = [ev(1, "bob", "refusal", "eingeschraenkt", "rechte Hand", window=win)]
        s, p = scene(facts)
        s["scene"] = {"placeId": "kueche"}
        self.assertEqual([x["einschraenkung"] for x in sc.restricted_refusals_standing(s, p)], ["rechte Hand"])
        s["scene"] = {"placeId": "garten"}
        self.assertEqual(sc.restricted_refusals_standing(s, p), [])

    def test_unconfirmed_part_never_becomes_permission(self):
        facts = [ev(1, "bob", "refusal", "jede_beruehrung"),
                 ev(2, "bob", "acceptance", "diese_tat", open_part="linke Hand")]
        snap = snapshot(sc, facts)
        self.assertEqual(snap["ausnahmen"], [("f2", "unbestaetigt")])
        self.assertEqual(snap["perms"], [])
        self.assertEqual(snap["state"], "declined")

    def test_other_side_is_distinct_across_all_readers(self):
        facts = [ev(1, "bob", "refusal", "eingeschraenkt", "rechte Hand"),
                 ev(2, "bob", "acceptance", "eingeschraenkt", "linke Hand")]
        snap = snapshot(sc, facts)
        self.assertEqual(snap["refs"], ["rechte Hand"])
        self.assertEqual(snap["perms"], ["linke Hand"])
        assert_cross_invariants(self, snap, facts)

    def test_sps_v65x_revoke_without_part_ends_broad_permission(self):
        """SPS V65X Z. 1414: "ein Widerruf ohne Stelle beendet eine Erlaubnis
        weiterhin (vorsichtige Richtung, Z. 1974)"."""
        facts = [ev(1, "bob", "acceptance", "jede_beruehrung"), ev(2, "bob", "revoke", "diese_tat")]
        snap = snapshot(sc, facts)
        self.assertEqual((snap["state"], snap["cause"]), ("revoked", "f2"))
        self.assertEqual(snapshot(orig, facts), snap)   # unveraendertes V67-Verhalten

    def test_sps_v65x_revoke_of_same_part_ends_only_that_part(self):
        """SPS V65X E01: "Widerruf nur der einen Stelle"."""
        facts = [ev(1, "bob", "acceptance", "eingeschraenkt", "rechte Hand"),
                 ev(2, "bob", "acceptance", "eingeschraenkt", "Schulter"),
                 ev(3, "bob", "revoke", "eingeschraenkt", "meine rechte Hand")]
        self.assertEqual(snapshot(sc, facts)["perms"], ["Schulter"])

    def test_compound_word_is_not_same_part(self):
        facts = [ev(1, "bob", "refusal", "eingeschraenkt", "Hand"),
                 ev(2, "bob", "acceptance", "eingeschraenkt", "Handtasche")]
        snap = snapshot(sc, facts)
        self.assertEqual(snap["refs"], ["Hand"])
        self.assertEqual(snap["perms"], ["Handtasche"])


class OriginalV67DifferentialTests(unittest.TestCase):
    """Gleiche Kette gegen rekonstruierten Original-Reader.

    Erwartung: Abweichungen genau dort, wo V67 nachweislich falsch ist
    (C04-Klassen: fremder/leerer Sprecher, abgelaufene Ereignisse).
    Das ist ein Altfehler-Nachweis, KEIN Kandidaten-Gruen.
    """

    C04 = [
        ("C04_WRONG_GIVER_BROAD",
         [ev(1, "bob", "refusal", "jede_beruehrung"), ev(2, "alice", "acceptance", "jede_beruehrung")],
         "state", "declined"),
        ("C04_EXPIRED_BROAD_ACCEPTANCE",
         [ev(1, "bob", "refusal", "jede_beruehrung"),
          ev(2, "bob", "acceptance", "jede_beruehrung", window=EXPIRED)],
         "state", "declined"),
        ("C04_EXPIRED_NARROW_REFUSAL",
         [ev(1, "bob", "acceptance", "eingeschraenkt", "rechte Hand"),
          ev(2, "bob", "refusal", "eingeschraenkt", "rechte Hand", window=EXPIRED)],
         "perms", ["rechte Hand"]),
        ("C04_EXPIRED_NARROW_ACCEPTANCE",
         [ev(1, "bob", "refusal", "eingeschraenkt", "rechte Hand"),
          ev(2, "bob", "acceptance", "eingeschraenkt", "rechte Hand", window=EXPIRED)],
         "refs", ["rechte Hand"]),
    ]

    def test_c04_candidate_green_original_red(self):
        for name, facts, key, goal in self.C04:
            with self.subTest(case=name):
                self.assertEqual(snapshot(sc, facts)[key], goal, "Kandidat (Rust) verfehlt SOLL")
                self.assertNotEqual(snapshot(orig, facts)[key], goal, "Original-V67 sollte hier rot sein")

    def test_timeline_divergence_only_on_known_defect_classes(self):
        """Pro Zeitschritt: Wo Original und Kandidat abweichen, muss das
        ausloesende Ereignis zur C04-Defektklasse gehoeren."""
        facts, divergent = [], []
        for event, _ in TIMELINE:
            facts.append(event)
            if snapshot(sc, facts) != snapshot(orig, facts):
                divergent.append(event["id"])
        defect = {e["id"] for e, _ in TIMELINE
                  if e["actorId"] != "bob"
                  or (e["payload"]["koerperkontakt"].get("window") or {}) == EXPIRED}
        # Folge-Abweichungen nach einem Defekt-Ereignis sind erlaubt (Zustand bereits verschieden);
        # die ERSTE Abweichung muss aber von einem Defekt-Ereignis kommen.
        self.assertTrue(divergent, "kein Unterschied: Reparatur wirkungslos?")
        self.assertIn(divergent[0], defect)
        self.divergent = divergent


if __name__ == "__main__":
    unittest.main(verbosity=2)
