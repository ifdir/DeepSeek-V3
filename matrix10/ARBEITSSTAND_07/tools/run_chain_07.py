#!/usr/bin/env python3
"""Arbeitsstand 07 - EIN Gesamtlauf: K-01 (serverseitige TurnTruth- und Commit-Bindung, W2) + SEC (Schluessel-Leck) auf P25 + 06a.

Exitcode = VERTRAGSSTATUS (verbindlich): 0 GRUEN, 2 ROT, 3 BLOCKIERT. ROT hat Vorrang vor BLOCKIERT.
Uebernimmt ALLE Stufen der 06-Kette (0, A, B, C, D, D2, D3, K2a, D3F, E, F, G) auf Stage 07 und ergaenzt:
  K    K-01/SEC-Gegenproben (tests/test_k01_turntruth_07.py, test_sec_mcc_07.py, test_k01_p18_portiert_07.py)
  AUS  Ausgangsnachweis: dieselben Proben auf Stage 06a (ohne K-01/SEC) muessen den Defekt zeigen
  MUT  Mutationsgegenprobe (mutation_07.py): jede reparierte Schutzregel einzeln entfernt -> Tests ROT
  LIVE echter Startweg START.py + gebautes Frontend + Chromium + Neustart + Folgeturn + Faelschungen + Leck
Aufruf: python3 -B tools/run_chain_07.py [--ohne-frontend]
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

HIER = Path(__file__).resolve().parents[1]                 # matrix10/ARBEITSSTAND_07
TOOLS6 = HIER.parent / "ARBEITSSTAND_06" / "tools"          # unveraenderte 06-Werkzeuge
TOOLS = HIER / "tools"
EVID = HIER / "evidence" / "chain_07"
P25_ZIP = HIER.parent / "MATRIX10_FREIGABESPERRE_P25_V1_20261107/MATRIX10_FREIGABESPERRE_P25_V1/MATRIX10_V92_P25_QUELLREPARATUR_ROT_20261107.zip"
P25_DIR = "MATRIX10_V92_P25_QUELLREPARATUR_ROT_20261107"
LIB = "libmatrix_boundary_core.so"
PY = [sys.executable, "-I"]


def sh(cmd, cwd=None, timeout=1800, env=None):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
    return r.returncode, r.stdout + r.stderr


def build_lib(crate: Path, abi: int | None = None) -> Path:
    if abi is not None:
        lib_rs = crate / "src/lib.rs"
        lib_rs.write_text(re.sub(r"pub const ABI_VERSION: u32 = \d+;", f"pub const ABI_VERSION: u32 = {abi};", lib_rs.read_text()))
    code, out = sh(["cargo", "build", "--release", "--offline", "--locked"], cwd=crate)
    if code:
        raise RuntimeError("cargo build fehlgeschlagen:\n" + out[-2000:])
    return crate / "target/release" / LIB


def stage(ziel: Path, skript: str = "07") -> Path:
    s = TOOLS / "stage_source_07.py" if skript == "07" else TOOLS6 / "stage_source_06.py"
    code, out = sh(PY + [str(s), str(P25_ZIP), str(ziel)])
    if code:
        raise RuntimeError("Stage fehlgeschlagen: " + out)
    return ziel / P25_DIR


def install_lib(root: Path, lib: Path | None):
    nat = root / "matrix_api/native"
    shutil.rmtree(nat, ignore_errors=True)
    if lib is not None:
        nat.mkdir(parents=True)
        shutil.copy2(lib, nat / LIB)


def probe_consent(root: Path, label: str, out: Path) -> dict:
    code, log = sh(PY + [str(TOOLS6 / "probe_p25_consent_06.py"), "--root", str(root), "--output", str(out), "--label", label])
    if code:
        raise RuntimeError("Einwilligungsprobe gescheitert:\n" + log[-2000:])
    return json.loads(out.read_text())


def junit(p: Path) -> dict:
    res = {}
    for tc in ET.parse(p).getroot().iter("testcase"):
        st = "pass"
        for ch in tc:
            if ch.tag in ("failure", "error"):
                st = ch.tag
            elif ch.tag == "skipped":
                st = "skip"
        res[tc.get("classname", "") + "::" + tc.get("name", "")] = st
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ohne-frontend", action="store_true")
    a = ap.parse_args()
    EVID.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="matrix06_chain_"))
    T: dict = {}            # teilpruefungen
    V: dict = {}            # vertragsstatus je Punkt

    def schreiben(gesamt, exitcode):
        rep = {"stand": "07", "einordnung": "K-01 TurnTruth/Commit-Bindung + SEC auf P25 + 06a; Gesamtprodukt ROT, keine Produktfreigabe",
               "product_release": False, "teilpruefungen": T, "vertragsstatus": V,
               "vertragsstatus_gesamt": gesamt, "exitcode": exitcode}
        (EVID / "result_07.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return rep

    try:
        # ---------- 0
        root = stage(tmp / "stage")
        p25 = tmp / "p25"
        p25.mkdir()
        sh(["unzip", "-q", str(P25_ZIP), "-d", str(p25)])
        p25 = p25 / P25_DIR
        man = json.loads((tmp / "stage/STAGE_07_MANIFEST.json").read_text())
        s07 = man.get("stand_07") or {}
        T["0_integritaet"] = {"status": "PASS" if len(s07.get("overlay_07") or {}) == 6 and not s07.get("ausgelassen") else "ROT",
                              "basis_sha256": man["basis_sha256"], "ersetzt_06": man["ersetzt_original_sha256"],
                              "overlay_06_dateien": len(man["overlay_sha256"]), "overlay_07": s07.get("overlay_07")}

        # ---------- A
        code, out = sh(PY + ["-c", (
            "import sys; sys.path.insert(0, sys.argv[1]);"
            "from matrix_api import scene_state as sc, native_boundary as nb;"
            "s={'facts':[{'id':'f1','kind':'lifecycle','event_kind':'refusal','actorId':'m','propositionId':'p','validated':True,"
            "'turn':1,'payload':{'koerperkontakt':{'scope':'jede_beruehrung'}}}],'propositions':[{'id':'p','kind':'koerperkontakt','actorId':'j','targetId':'m'}]};"
            "p=s['propositions'][0]\n"
            "for fn in (sc.body_contact_standing, sc.restricted_refusals_standing, sc.restricted_permissions_standing):\n"
            "    try: fn(s,p); print('ENTSCHIEDEN', fn.__name__)\n"
            "    except nb.NativeBoundaryError as e: print('FAILCLOSED', fn.__name__, e.code, e.status)"), str(root)])
        ok_a = out.count("FAILCLOSED") == 3 and "ENTSCHIEDEN" not in out and out.count("NATIVE_BOUNDARY_UNAVAILABLE 503") == 3
        T["A_fail_closed_ohne_bibliothek"] = {"status": "PASS" if ok_a else "ROT", "ausgabe": out.strip().splitlines()}

        # ---------- B / C
        crate = root / "native_core/matrix-boundary-core"
        code, out = sh(["cargo", "test", "--offline", "--locked"], cwd=crate)
        passed = sum(int(x) for x in re.findall(r"test result: ok\. (\d+) passed", out))
        failed = sum(int(x) for x in re.findall(r"(\d+) failed", out))
        (EVID / "B_cargo_test.log").write_text(out)
        T["B_cargo_test"] = {"status": "PASS" if code == 0 and failed == 0 and passed >= 86 else "ROT", "passed": passed, "failed": failed}
        lib = build_lib(crate)
        abi2_crate = tmp / "abi2"
        shutil.copytree(crate, abi2_crate, ignore=shutil.ignore_patterns("target"))
        lib2 = build_lib(abi2_crate, abi=2)
        install_lib(root, lib)
        env = dict(os.environ, MATRIX06_ROOT=str(root), MATRIX06_ABI2_LIB=str(lib2))
        code, out = sh(PY + [str(HIER.parent / "ARBEITSSTAND_06/tests/test_abi3_contract_06.py")], env=env)
        (EVID / "C_abi3_contract.log").write_text(out)
        ran = re.search(r"Ran (\d+) test", out)
        T["C_build_und_K1_abi3"] = {"status": "PASS" if code == 0 else "ROT", "abi3_tests": int(ran.group(1)) if ran else 0}

        # ---------- D / D2
        d = probe_consent(root, "Stage 07", EVID / "D_stage07_probe.json")
        d0 = probe_consent(p25, "P25 unveraendert", EVID / "D2_p25_probe.json")
        rot06 = set(d["rot"])
        T["D_einwilligungskette_stage07"] = {"status": "PASS" if not rot06 else "ROT",
                                             "soll_erfuellt": f"{d['soll_erfuellt']}/{d['gesamt']}", "rot": sorted(rot06)}
        verschlechtert = sorted(set(d["rot"]) - set(d0["rot"]))
        repariert = sorted(set(d0["rot"]) - set(d["rot"]))
        T["D2_differenz_p25"] = {"status": "PASS" if not verschlechtert else "ROT", "p25_rot": d0["rot"],
                                 "repariert": repariert, "verschlechtert": verschlechtert}

        # ---------- D3 HTTP + K2a
        vorlage = tmp / "vorlage.sqlite"
        res = {}
        for v in ("ok", "fehlt", "abi2"):
            args = PY + [str(TOOLS / "probe_http_503_07.py"), "--root", str(root), "--variante", v,
                         "--abi2-lib", str(lib2), "--output", str(EVID / f"D3_nachher_{v}.json")]
            args += ["--vorlage-ausgabe", str(vorlage)] if v == "ok" else ["--vorlage", str(vorlage)]
            code, out = sh(args, timeout=1200)
            if code:
                raise RuntimeError(f"HTTP-Probe {v}: " + out[-1500:])
            res[v] = json.loads((EVID / f"D3_nachher_{v}.json").read_text())["anfragen"]
        fehler = []
        for v, code_soll in (("fehlt", "NATIVE_BOUNDARY_UNAVAILABLE"), ("abi2", "NATIVE_ABI_MISMATCH")):
            for x in res[v]:
                if x["erreicht_native_grenze"]:
                    if not (x["status"] == 503 and x["code"] == code_soll and x["sqlite_unveraendert"] and not x["erfolgsmeldung"]):
                        fehler.append((v, x["anfrage"], x["status"], x["code"]))
                elif x.get("vorbereitung") not in (None, "belege"):
                    # K-01: ohne Belege (Vorbereitung im Ausfall abgelehnt) fruehe korrekte Ablehnung, nichts gespeichert
                    if not (x["status"] in (409, 422) and x["sqlite_unveraendert"] and not x["erfolgsmeldung"]):
                        fehler.append((v, x["anfrage"], "ohne Belege nicht fail-closed", x["status"]))
                else:
                    ref = next(y for y in res["ok"] if y["anfrage"] == x["anfrage"])
                    if x["status"] != ref["status"]:
                        fehler.append((v, x["anfrage"], "nicht erreicht, Status weicht ab", x["status"]))
        T["D3_http_503"] = {"status": "PASS" if not fehler else "ROT", "anfragen_je_variante": len(res["ok"]),
                            "ok_alle_200": all(x["status"] == 200 for x in res["ok"]), "abweichungen": fehler}
        sh(PY + [str(TOOLS6 / "inventar_swallow_06.py"), str(root), str(EVID / "K2a_inventar.json")])
        code, out = sh(PY + [str(TOOLS / "probe_failpoint_07.py"), "--root", str(root), "--vorlage", str(vorlage),
                             "--output", str(EVID / "K2a_failpoints.json")], timeout=3000)
        if code:
            raise RuntimeError("Fehlerinjektion: " + out[-1500:])
        inv = json.loads((EVID / "K2a_inventar.json").read_text())["laeuft_weiter"]
        fp = json.loads((EVID / "K2a_failpoints.json").read_text())["anfragen"]
        punkte = [p for x in fp for p in x["punkte"]]
        stellen = []
        for f in inv:
            rng = range(f["try_zeile"], f["try_ende"] + 1)
            pts = [p for x in fp for p in x["punkte"] if any(l in rng for l in (p["app_stapel_erster_fehler"] or []))]
            stellen.append({"stelle": f"{f['funktion']}:{f['handler_zeile']}",
                            "status": ("FAIL_OPEN" if any(p["fail_open"] for p in pts) else "BELEGT_FAIL_CLOSED") if pts else "BLOCKIERT_NICHT_ERREICHT",
                            "ausfallpunkte": len(pts)})
        fail_open = [p for p in punkte if p["fail_open"]]
        meldung_falsch = [(x["anfrage"], p["k"]) for x in fp for p in x["punkte"] if p.get("meldung_stimmt") is False]
        T["D3_K2a_verschluckte_pfade"] = {"status": "ROT" if fail_open or meldung_falsch or any(s["status"] == "FAIL_OPEN" for s in stellen) else "PASS",
                                          "m2_prepare_meldung_falsch": meldung_falsch,
                                          "ausfallpunkte": len(punkte), "fail_open": len(fail_open), "stellen": stellen,
                                          "teilcommit_vor_ausfall": sum(len(x.get("teilcommit_vor_ausfall") or []) for x in fp)}

        # ---------- D3F Frontend
        if a.ohne_frontend:
            T["D3F_frontend"] = {"status": "BLOCKIERT", "grund": "--ohne-frontend"}
            T["LIVE_k01_sec"] = {"status": "BLOCKIERT", "grund": "--ohne-frontend"}
        else:
            fe = tmp / "fe"
            shutil.copytree(root, fe, ignore=shutil.ignore_patterns("target"))
            c1, o1 = sh(["npm", "ci", "--no-audit", "--no-fund"], cwd=fe, timeout=1200)
            c2, o2 = sh(["npm", "run", "build:dist"], cwd=fe, timeout=1200) if c1 == 0 else (1, "")
            if c1 or c2:
                T["D3F_frontend"] = {"status": "BLOCKIERT", "grund": "npm ci / build:dist nicht moeglich", "log": (o1 + o2)[-800:]}
                T["LIVE_k01_sec"] = {"status": "BLOCKIERT", "grund": "npm ci / build:dist nicht moeglich"}
            else:
                nat_ok = tmp / "native_ok"
                shutil.copytree(fe / "matrix_api/native", nat_ok)
                ui = {}
                for v in ("ok", "fehlt", "abi2"):
                    install_lib(fe, None if v == "fehlt" else (lib2 if v == "abi2" else nat_ok / LIB))
                    c, o = sh(["bash", str(TOOLS6 / "ui_start.sh"), str(fe), str(vorlage), str(tmp / f"start_{v}.log")], timeout=120)
                    if c:
                        raise RuntimeError("UI-Start: " + o)
                    nodep = sh(["npm", "root", "-g"])[1].strip()
                    extra = (["--storage-out", str(tmp / "storage_admin.json")] if v == "ok"
                             else ["--storage-in", str(tmp / "storage_admin.json")])
                    c, o = sh(["node", str(TOOLS6 / "probe_frontend_503_06.cjs"), v, str(EVID / f"D3_frontend_{v}.json"),
                               str(EVID / f"D3_frontend_{v}")] + extra, env=dict(os.environ, NODE_PATH=nodep), timeout=300)
                    ui[v] = json.loads((EVID / f"D3_frontend_{v}.json").read_text())["handlungen"] if c == 0 else {"fehler": o[-800:]}
                sh(["bash", str(TOOLS6 / "ui_stop.sh")])
                # LIVE (K-01/SEC): derselbe gebaute Stand, echte Rust-Bibliothek, Vorlage aus D3
                install_lib(fe, nat_ok / LIB)
                c, o = sh(PY + [str(TOOLS / "live_abnahme_k01_07.py"), str(fe), str(vorlage), str(EVID / "live")], timeout=1800)
                lj = EVID / "live" / "L_abnahme_k01_07.json"
                T["LIVE_k01_sec"] = ({"status": "PASS" if c == 0 else ("ROT" if c == 2 else "BLOCKIERT"),
                                      "kriterien": json.loads(lj.read_text())["kriterien"]} if lj.exists()
                                     else {"status": "BLOCKIERT", "grund": o[-800:]})
                def h(v, name):
                    return next((x for x in ui.get(v) or [] if isinstance(x, dict) and x.get("handlung") == name), {})
                m3 = {
                    "ok_liste_sichtbar_ohne_fehler": bool(h("ok", "U0b_chat_seite").get("fall06_karte_sichtbar"))
                                                     and not h("ok", "U0b_chat_seite").get("sessions_ladefehler"),
                    "ok_leere_liste_zeigt_keine_session": bool(h("ok", "U4_nutzer_ohne_session").get("keine_session_sichtbar"))
                                                          and not h("ok", "U4_nutzer_ohne_session").get("sessions_ladefehler"),
                }
                for v in ("fehlt", "abi2"):
                    for n in ("U0b_chat_seite", "U3_neuladen_gespeicherter_nutzer"):
                        x = h(v, n)
                        m3[f"{v}_{n}_fehler_mit_code_keine_leer_kein_laedt"] = bool(
                            x.get("ladefehler_mit_code") and not x.get("keine_session_sichtbar") and not x.get("laedt_sichtbar")
                            and not any(y["status"] == 200 and y["url"].startswith("/api/mcc") for y in x.get("api") or []))
                ok_fe = all(m3.values())
                T["D3F_frontend"] = {"status": "PASS" if ok_fe else "ROT", "m3_kriterien": m3,
                                     "kurz": {v: [(h["handlung"], h.get("sichtbar_fehler"), h.get("nicht_bedienbar")) for h in ui[v]]
                                              if isinstance(ui[v], list) else ui[v] for v in ui}}

        # ---------- E Gegenprobe
        mut = {
            "rust_ohne_sprecherbindung": ("native_core/matrix-boundary-core/src/consent.rs", "e.active && e.by == giver", "e.active"),
            "rust_ohne_gueltigkeitsfenster": ("native_core/matrix-boundary-core/src/consent.rs", "e.active && e.by == giver", "e.by == giver"),
            "rust_taetantwort_hebt_grenze_auf": ("native_core/matrix-boundary-core/src/consent.rs",
                                                 'if broad_kind == "refusal" && is_act_answer_against(&e) {', "if false {"),
            "rust_taetantwort_ohne_bindung": ("native_core/matrix-boundary-core/src/consent.rs", "!e.acts_bound || e.acts.iter()", "true || e.acts.iter()"),
            "python_lifecycle_bound_ohne_giverregel": ("matrix_api/scene_state.py",
                                                       '        return actor == str(props[pid].get("targetId") or "")', "        pass"),
        }
        erkannt = {}
        for name, (rel, alt, neu) in mut.items():
            mroot = stage(tmp / f"mut_{name}")
            f = mroot / rel
            t = f.read_text()
            if t.count(alt) != 1:
                erkannt[name] = {"erkannt": False, "grund": "Mutationsanker nicht eindeutig"}
                continue
            f.write_text(t.replace(alt, neu))
            mlib = build_lib(mroot / "native_core/matrix-boundary-core") if rel.endswith(".rs") else lib
            install_lib(mroot, mlib)
            md = probe_consent(mroot, f"Mutation {name}", tmp / f"mut_{name}.json")
            erkannt[name] = {"erkannt": md["soll_erfuellt"] < d["soll_erfuellt"], "soll_erfuellt": f"{md['soll_erfuellt']}/{md['gesamt']}",
                             "neu_rot": sorted(set(md["rot"]) - rot06)}
        # 06a / M1: die Rust-Sprecherbindung muss in Rusts EIGENEN Tests durchgesetzt sein (cargo test wird rot) ...
        uroot = stage(tmp / "mut_unit_sprecher")
        f = uroot / "native_core/matrix-boundary-core/src/consent.rs"
        f.write_text(f.read_text().replace("e.active && e.by == giver", "e.active", 1))
        code_u, out_u = sh(["cargo", "test", "--offline", "--locked"], cwd=uroot / "native_core/matrix-boundary-core")
        rote_tests = sorted(set(re.findall(r"test (\S+) \.\.\. FAILED", out_u)))
        (EVID / "E_rust_unit_sprecherbindung.log").write_text(out_u)
        # ... und die P25-Kette bleibt fail-closed, auch wenn Python- UND Rust-Schicht fehlen (kombinierte Gegenprobe)
        kroot = stage(tmp / "mut_kombiniert")
        for rel, alt, neu in (("native_core/matrix-boundary-core/src/consent.rs", "e.active && e.by == giver", "e.active"),
                              ("matrix_api/scene_state.py", '        return actor == str(props[pid].get("targetId") or "")', "        pass")):
            ff = kroot / rel
            ff.write_text(ff.read_text().replace(alt, neu, 1))
        install_lib(kroot, build_lib(kroot / "native_core/matrix-boundary-core"))
        kd = probe_consent(kroot, "Mutation Rust+Python ohne Sprecherbindung", EVID / "E_kombiniert_sprecherbindung.json")
        fg = next(c for c in kd["faelle"] if c["fall"] == "C04_FREMDER_GIVER")
        kombiniert_fail_closed = (fg["lesen"].get("state") != "accepted"
                                  and (fg["lesen"].get("acts") or {}).get("a3") != "accepted")
        T["E_gegenprobe"] = {"status": "PASS" if all(x["erkannt"] for x in erkannt.values()) else "ROT", "mutationen": erkannt,
                             "hinweis": "Rust-only-Sprecherbindung ueber die P25-Kette nicht beobachtbar (verdeckt durch "
                                        "lifecycle_bound + _checked_index); Redundanz vom Nutzer als verbindlich entschieden",
                             "rust_unit_sprecherbindung": {"cargo_test_rot": code_u != 0, "rote_tests": rote_tests,
                                                           "status": "PASS" if code_u != 0 and rote_tests else "ROT"},
                             "kombiniert_fail_closed": {"status": "PASS" if kombiniert_fail_closed else "ROT",
                                                        "c04_fremder_giver": fg["befunde"]}}

        # ---------- F
        r = {}
        for lbl, rr in (("p25", p25), ("stage07", root)):
            sh([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--continue-on-collection-errors", "tests",
                f"--junitxml={tmp / (lbl + '.xml')}"], cwd=rr, timeout=2400)
            r[lbl] = junit(tmp / (lbl + ".xml"))
        abw = sorted(k for k in set(r["p25"]) | set(r["stage07"]) if r["p25"].get(k) != r["stage07"].get(k))
        rot_p25 = sorted(k for k, v in r["p25"].items() if v != "pass")
        # K-01: genau dieser P25-Test schickt eine selbst erzeugte Figurenantwort an commit (der reparierte Defektpfad). Er wird
        # NICHT angepasst; seine Assertions laufen unveraendert ueber den Produktweg in tests/test_k01_p18_portiert_07.py (Stufe K).
        vertragsbedingt = {"tests.test_v92_p18_koerper.P18AvatarAndFigure::test_avatar_position_and_figure_reply_with_forged_and_real_readings"}
        unerklaert = [k for k in abw if not (k in vertragsbedingt and r["p25"].get(k) == "pass" and r["stage07"].get(k) == "failure")]
        T["F_p25_testsuite"] = {"status": "PASS" if not unerklaert else "ROT",
                                "p25": {s: list(r["p25"].values()).count(s) for s in set(r["p25"].values())},
                                "stage07": {s: list(r["stage07"].values()).count(s) for s in set(r["stage07"].values())},
                                "abweichungen": abw, "vertragsbedingt_k01": sorted(set(abw) & vertragsbedingt),
                                "unerklaert": unerklaert, "p25_altbefunde_rot": rot_p25}

        # ---------- K / AUS / MUT (K-01 + SEC)
        kt = [str(HIER / "tests" / n) for n in ("test_k01_turntruth_07.py", "test_sec_mcc_07.py", "test_k01_p18_portiert_07.py")]
        code, out = sh([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *kt], cwd=root / "tests",
                       env=dict(os.environ, MATRIX07_ROOT=str(root)), timeout=1800)
        (EVID / "K_tests.log").write_text(out)
        T["K_k01_sec_tests"] = {"status": "PASS" if code == 0 else "ROT", "zusammenfassung": out.strip().splitlines()[-1:]}
        r06 = stage(tmp / "stage06a", "06")
        install_lib(r06, lib)
        aus = {}
        for lbl, rr in (("ohne_k01_06a", r06), ("mit_k01_07", root)):
            sh(PY + [str(TOOLS / "probe_ausgang_k01_07.py"), str(rr), str(EVID / f"AUS_{lbl}.json")], timeout=600)
            aus[lbl] = json.loads((EVID / f"AUS_{lbl}.json").read_text())
        code, out = sh([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *kt[:2]], cwd=r06 / "tests",
                       env=dict(os.environ, MATRIX07_ROOT=str(r06)), timeout=1800)
        (EVID / "AUS_tests_auf_06a.log").write_text(out)
        a06 = aus["ohne_k01_06a"]
        T["AUS_ausgangsnachweis_06a"] = {
            "status": "PASS" if (a06["H1"].get("mara_als_zeugin_trotz_leerer_hoererliste") and a06["S1_proposals_synapsen"].get("runtime_geaendert")
                                 and code != 0) else "ROT",
            "hoerer_rueckfall_06a": a06["H1"].get("mara_als_zeugin_trotz_leerer_hoererliste"),
            "client_proposals_synapsen_aendern_runtime_06a": a06["S1_proposals_synapsen"].get("runtime_geaendert"),
            "client_fired_aendert_runtime_06a": a06["S2_fired"].get("runtime_geaendert"),
            "k01_tests_auf_06a": out.strip().splitlines()[-1:]}
        code, out = sh(PY + [str(TOOLS / "mutation_07.py"), str(root), str(EVID / "MUT_mutation_07.json")], timeout=5400)
        mj = json.loads((EVID / "MUT_mutation_07.json").read_text())
        T["MUT_mutationsgegenprobe"] = {"status": "PASS" if mj.get("alle_erkannt") else "ROT",
                                        "mutationen": {k: v.get("erkannt") for k, v in mj["mutationen"].items()}}

        # ---------- G
        orig_db = os.environ.get("MATRIX10_ORIGINAL_DB")
        key = os.environ.get("MATRIX10_PROVIDER_KEY_VORHANDEN")
        T["G_pruefmaschine_v12"] = {"status": "BLOCKIERT", "grund": [g for g, fehlt in (
            ("Original-DB e03dc445... fehlt", not orig_db), ("Modell-/Providerschluessel fuer --modell live fehlt", not key),
            ("P23/P24/P25-Selbstabnahme-ZIPs nicht vorhanden", True)) if fehlt]}

        # ---------- Vertragsstatus (AMASTER / Kettenvertrag)
        V["C04_fremder_giver_und_abgelaufene_fenster"] = "GRUEN" if not ({"C04_FREMDER_GIVER", "C04_ABGELAUFENE_BREITE_ZUSTIMMUNG",
                                                                         "C04_ABGELAUFENE_EINZELABLEHNUNG", "C04_ABGELAUFENE_EINZELZUSTIMMUNG"} & rot06) else "ROT"
        V["S05_tat_antwort_hebt_keine_grenze_auf"] = "GRUEN" if not ({"S05_WIDERRUF_DER_AUSNAHME", "S05_ANDERE_STELLE"} & rot06) else "ROT"
        V["W1_W3_schreibgrenze_giver_und_proposition"] = "GRUEN" if not ({"C04_FREMDER_GIVER", "W3_OHNE_PROPOSITION"} & rot06) else "ROT"
        _mut = T["MUT_mutationsgegenprobe"]["mutationen"]
        V["W2_lifecycle_evidenz_eigene_aeusserung"] = ("GRUEN" if "W2_ACTOR_NICHT_SPRECHER" not in rot06 and T["K_k01_sec_tests"]["status"] == "PASS"
                                                      and all(_mut.get(m) for m in ("M7_w2_fremde_evidenz_kernel", "M8_w2_status_ohne_evidenz",
                                                                                     "M9_w2_leseseite", "M9b_w2_quellturn_regel")) else "ROT")
        V["K1_abi3"] = "GRUEN" if T["C_build_und_K1_abi3"]["status"] == "PASS" else "ROT"
        V["K2_http_503"] = "GRUEN" if T["D3_http_503"]["status"] == "PASS" else "ROT"
        V["K2a_verschluckte_pfade"] = ("ROT" if T["D3_K2a_verschluckte_pfade"]["status"] == "ROT" else
                                      ("BLOCKIERT" if any(s["status"].startswith("BLOCKIERT") for s in stellen) else "GRUEN"))
        V["K2_frontend_fehler_sichtbar"] = {"PASS": "GRUEN", "ROT": "ROT"}.get(T["D3F_frontend"]["status"], "BLOCKIERT")
        V["P25_altbefunde_testsuite"] = "ROT" if T["F_p25_testsuite"]["p25_altbefunde_rot"] else "GRUEN"
        V["modell_folgeturn_live"] = "BLOCKIERT"
        V["pruefmaschine_v12_achsen"] = "BLOCKIERT"
        V["M1_rust_sprecherbindung_eigene_tests"] = T["E_gegenprobe"]["rust_unit_sprecherbindung"]["status"].replace("PASS", "GRUEN")
        V["M1_kette_fail_closed_ohne_python_und_rust_schicht"] = T["E_gegenprobe"]["kombiniert_fail_closed"]["status"].replace("PASS", "GRUEN")
        V["M1_rust_only_mutation_ueber_kette"] = "ROT" if not erkannt["rust_ohne_sprecherbindung"]["erkannt"] else "GRUEN"
        V["M2_prepare_meldung_teilcommit"] = "GRUEN" if not meldung_falsch else "ROT"
        V["M3_chatliste_fehler_statt_leer"] = {"PASS": "GRUEN", "ROT": "ROT"}.get(T["D3F_frontend"]["status"], "BLOCKIERT")
        _k = T["K_k01_sec_tests"]["status"] == "PASS" and T["MUT_mutationsgegenprobe"]["status"] == "PASS"
        _live = T.get("LIVE_k01_sec", {}).get("status")
        V["K01_turntruth_und_commit_bindung_offline"] = ("GRUEN" if _k and _live == "PASS" and T["AUS_ausgangsnachweis_06a"]["status"] == "PASS"
                                                         else ("BLOCKIERT" if _k and _live == "BLOCKIERT" else "ROT"))
        V["K01_formulierung_mit_echtem_modell"] = "BLOCKIERT"
        V["SEC_kein_schluessel_in_antworten_browser_logs"] = ("GRUEN" if _k and _live == "PASS" else ("BLOCKIERT" if _k and _live == "BLOCKIERT" else "ROT"))
        V["P25_test_verlangt_defektpfad_portiert"] = "GRUEN" if T["F_p25_testsuite"]["status"] == "PASS" and T["K_k01_sec_tests"]["status"] == "PASS" else "ROT"
        technisch_rot = [k for k, x in T.items() if isinstance(x, dict) and x.get("status") == "ROT"]
        werte = list(V.values())
        gesamt = "ROT" if ("ROT" in werte or technisch_rot) else ("BLOCKIERT" if ("BLOCKIERT" in werte or "OFFEN" in werte) else "GRUEN")
        exitcode = {"GRUEN": 0, "ROT": 2, "BLOCKIERT": 3}[gesamt]
        rep = schreiben(gesamt, exitcode)
    except Exception as e:
        T["abbruch"] = {"status": "BLOCKIERT", "grund": f"{type(e).__name__}: {e}"[:3000]}
        rep = schreiben("BLOCKIERT", 3)
    print(json.dumps({"teilpruefungen": {k: v.get("status") for k, v in T.items()}, "vertragsstatus": V,
                      "gesamt": rep["vertragsstatus_gesamt"], "exitcode": rep["exitcode"]}, indent=2, ensure_ascii=False))
    shutil.rmtree(tmp, ignore_errors=True)
    return rep["exitcode"]


if __name__ == "__main__":
    raise SystemExit(main())
