#!/usr/bin/env python3
"""Run the actual Rust FFI + existing canonical SQLite Writer/Reader, NO mocks.

Requires a compiled native library installed by tools/build_native.py.
Exit 3 (BLOCKIERT) when absent/ABI wrong. Exit 1 (ROT) when any contract
breaks. Exit 0 means only this narrow test set passed, NOT AMASTER release.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sqlite3
import sys
import tempfile

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE/'tests'))
from original_boundary_harness import load_reference, create_fixture


def run(args):
    root=Path(args.staged_root).resolve();target=Path(args.output).resolve()
    target.parent.mkdir(parents=True,exist_ok=True)
    sys.path.insert(0,str(root))
    from matrix_api.native_boundary import _load, library_path
    if not library_path().is_file():
        r={"status":"BLOCKIERT","reason":"No compiled Rust library; no native code executed",
           "tests_executed":0,"product_release":False}
        target.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r));return 3
    try:_load()
    except Exception as exc:
        r={"status":"BLOCKIERT","reason":"Rust library cannot load/ABI invalid: "+str(exc),
           "tests_executed":0,"product_release":False}
        target.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r));return 3
    repo,db=load_reference(root)
    from matrix_api import scene_state
    results=[]
    def result(name,ok,details):results.append({"name":name,"passed":bool(ok),"details":details})
    with tempfile.TemporaryDirectory(prefix='matrix03_native_sqlite_') as tmp:
        tmp=Path(tmp)
        def fixture(name):
            path=tmp/(name+'.sqlite')
            return path,create_fixture(path,db)
        def reopen(path,conn):
            conn.commit();conn.close()
            c=sqlite3.connect(path);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');return c
        def tt(**changes):
            row={'id':'tt_a','role':'avatar','authority':'avatar','speaker_id':'alice',
                 'present_ids':['alice','bob'],'hears_ids':['alice'],'sees_ids':['alice'],'turn':1}
            return {**row,**changes}
        for key,change in (
            ('B01_scalar_perception',{'present_ids':'outsider'}),
            ('B02_god_speaker_alias',{'role':'god','authority':'god','speaker_id':None,'speakerId':'alice'}),
            ('P02_foreign_witness',{'sees_ids':['not_in_this_world']}),
        ):
            path,conn=fixture(key)
            failure=None
            try:repo.append_session_turn_truth(conn,'session_A',tt(**change),'usr_A')
            except repo.WriterError as exc:failure={'code':exc.error,'status':exc.status}
            conn=reopen(path,conn)
            exists=conn.execute('SELECT COUNT(*) FROM turn_truth').fetchone()[0]
            good=failure is not None and failure['status']==422 and failure['code']!='NATIVE_BOUNDARY_UNAVAILABLE' and exists==0
            result(key,good,{'error':failure,'stored_after_reopen':exists})
            conn.close()
        path,conn=fixture('B03_fact_actor_alias')
        repo.append_session_turn_truth(conn,'session_A',tt(),'usr_A')
        failure=None
        try:repo.append_session_fact(conn,'session_A',{'id':'f_bad','actorId':'alice','actor_id':'foreign',
             'targetId':'bob','sourceTurnId':'tt_a','turn':2},'usr_A')
        except repo.WriterError as exc:failure={'code':exc.error,'status':exc.status}
        conn=reopen(path,conn)
        got=conn.execute("SELECT COUNT(*) FROM scene_facts WHERE id='f_bad'").fetchone()[0]
        result('B03_fact_actor_alias',failure is not None and failure['status']==422 and got==0,
               {'error':failure,'stored_after_reopen':got})
        conn.close()
        path,conn=fixture('P01_valid_truth')
        fail=None
        try:repo.append_session_turn_truth(conn,'session_A',tt(),'usr_A')
        except repo.WriterError as exc:fail={'code':exc.error,'status':exc.status}
        conn=reopen(path,conn)
        reader=repo.get_session(conn,'usr_A','session_A')
        got=conn.execute('SELECT COUNT(*) FROM turn_truth').fetchone()[0]
        result('P01_valid_truth',fail is None and got==1 and len(reader.get('turnTruths') or [])==1,
               {'error':fail,'stored':got,'reader_rows':len(reader.get('turnTruths') or [])})
        conn.close()
        path,conn=fixture('B04_restriction_reducer')
        prop={'id':'prop_touch','kind':'koerperkontakt','actorId':'alice','targetId':'bob','state':'open'}
        repo.create_session_proposition(conn,'session_A',prop,'usr_A')
        for i,kind,part in [(1,'refusal','rechte Hand'),(2,'acceptance','linke Hand')]:
            repo.append_session_turn_truth(conn,'session_A',tt(id=f'tt_{i}',speaker_id='bob',turn=i),'usr_A')
            repo.append_session_fact(conn,'session_A',{'id':f'f_{i}','kind':'lifecycle','event_kind':kind,
                 'actorId':'bob','targetId':'alice','sourceTurnId':f'tt_{i}',
                 'propositionId':'prop_touch','validated':True,'turn':i,
                 'payload':{'koerperkontakt':{'scope':'eingeschraenkt','einschraenkung':part,'beleg':part}}},'usr_A')
        conn=reopen(path,conn)
        session=repo.get_session(conn,'usr_A','session_A')
        p=next(p for p in session['propositions'] if p.get('id')=='prop_touch')
        standing=[e['einschraenkung'] for e in scene_state.restricted_refusals_standing(session,p)]
        other=repo.get_session(conn,'usr_B','session_B')
        result('B04_restriction_reducer',standing==['rechte Hand'] and len(session.get('facts') or [])==2
               and len(other.get('facts') or [])==0,
               {'standing':standing,'original_fact_count':len(session.get('facts') or []),'foreign_fact_count':len(other.get('facts') or [])})
        conn.close()
        # V04 full SQLite check of additional CURRENT STATE counterprobes.
        # With a native library, none of these is a mock or an oracle.
        for name, second_actor, scope, part, timed, goal in (
            ("C04_WRONG_GIVER_BROAD", "alice", "jede_beruehrung", "", False, "declined"),
            ("C04_EXPIRED_BROAD_ACCEPTANCE", "bob", "jede_beruehrung", "", True, "declined"),
            ("C04_EXPIRED_NARROW_ACCEPTANCE", "bob", "eingeschraenkt", "rechte Hand", True, "right_refusal"),
            ("C04_EXPIRED_NARROW_REFUSAL", "bob", "eingeschraenkt", "rechte Hand", True, "right_permission"),
        ):
            path,conn=fixture(name)
            repo.create_session_proposition(conn,'session_A',{'id':'prop04','kind':'koerperkontakt',
                'actorId':'alice','targetId':'bob','state':'open'},'usr_A')
            order=((1,'bob','acceptance'),(2,second_actor,'refusal')) if goal=='right_permission' else ((1,'bob','refusal'),(2,second_actor,'acceptance'))
            for idx,who,kind in order:
                repo.append_session_turn_truth(conn,'session_A',tt(id=f'c04tt{idx}',
                    speaker_id=who,turn=idx),'usr_A')
                window=({'art':'zeit','start':'2026-11-01T12:00','end':'2026-11-01T13:00'}
                        if timed and idx==2 else None)
                repo.append_session_fact(conn,'session_A',{'id':f'c04f{idx}',
                    'kind':'lifecycle','event_kind':kind,'actorId':who,'targetId':'alice',
                    'sourceTurnId':f'c04tt{idx}','propositionId':'prop04',
                    'validated':True,'turn':idx,'payload':{'koerperkontakt':{
                        'scope':scope,'einschraenkung':part if scope=='eingeschraenkt' else None,
                        'window':window,'beleg':'native'}}},'usr_A')
            conn=reopen(path,conn)
            session=repo.get_session(conn,'usr_A','session_A')
            prop=next(p for p in session['propositions'] if p['id']=='prop04')
            at='2026-11-07T12:00'
            if goal=='right_permission':
                actual=[x['einschraenkung'] for x in scene_state.restricted_permissions_standing(session,prop,at=at)]
                expected=['rechte Hand']
            elif goal=='right_refusal':
                actual=[x['einschraenkung'] for x in scene_state.restricted_refusals_standing(session,prop,at=at)]
                expected=['rechte Hand']
            else:
                actual=(scene_state.body_contact_standing(session,prop,at=at) or {}).get('state')
                expected=goal
            rows=conn.execute('SELECT COUNT(*) FROM scene_facts WHERE session_id=?',('session_A',)).fetchone()[0]
            other=repo.get_session(conn,'usr_B','session_B')
            result(name, actual==expected and rows==2 and not other.get('facts'),
                   {'expected':expected,'actual':actual,'stored_after_reopen':rows,
                    'unrelated_facts':len(other.get('facts') or [])})
            conn.close()
    all_pass=all(item['passed'] for item in results)
    summary={'status':'NARROW_NATIVE_SQLITE_PASS_NOT_PRODUCT_RELEASE' if all_pass else 'ROT',
             'rust_loaded':True,'cases_executed':len(results),
             'passed':sum(x['passed'] for x in results),'failed':sum(not x['passed'] for x in results),
             'checks':results,'product_release':False,
             'not_proven':['HTTP UI','model output','BrainContext','full component commit','follow-up turn','process restart','AMASTER all 70','V12 16 axes']}
    target.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':summary['status'],'passed':summary['passed'],'failed':summary['failed'],'output':str(target)},ensure_ascii=False))
    return 0 if all_pass else 1

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('staged_root');p.add_argument('--output',required=True)
    sys.exit(run(p.parse_args()))
