#!/usr/bin/env python3
"""Independent V67 witness of current-state defects through actual SQLite I/O.

Reads unchanged V67 repository functions via the existing isolated import
harness, runs their real writers and read projections, closes and reopens DB.
NO native Rust call, NO write to product DB. These checks are EXPECTED RED.
"""
from __future__ import annotations
import argparse
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from original_boundary_harness import create_fixture, load_reference


def run(root: Path, output: Path):
    repo,db=load_reference(root)
    from matrix_api import scene_state as sc
    out=[]
    with tempfile.TemporaryDirectory(prefix='matrix_v67_consent04_') as d:
        for name,first,second,at,expected in (
            ('C04_WRONG_GIVER_BROAD',('bob','refusal','jede_beruehrung',None,None),
             ('alice','acceptance','jede_beruehrung',None,None),None,'declined'),
            ('C04_EXPIRED_BROAD_ACCEPTANCE',('bob','refusal','jede_beruehrung',None,None),
             ('bob','acceptance','jede_beruehrung',None,{'art':'zeit','start':'2026-11-01T12:00','end':'2026-11-01T13:00'}),
             '2026-11-07T12:00','declined'),
            ('C04_EXPIRED_NARROW_REFUSAL',('bob','acceptance','eingeschraenkt','rechte Hand',None),
             ('bob','refusal','eingeschraenkt','rechte Hand',{'art':'zeit','start':'2026-11-01T12:00','end':'2026-11-01T13:00'}),
             '2026-11-07T12:00','right_permission'),
            ('C04_EXPIRED_NARROW_ACCEPTANCE',('bob','refusal','eingeschraenkt','rechte Hand',None),
             ('bob','acceptance','eingeschraenkt','rechte Hand',{'art':'zeit','start':'2026-11-01T12:00','end':'2026-11-01T13:00'}),
             '2026-11-07T12:00','right_refusal'),
        ):
            path=Path(d)/(name+'.sqlite')
            conn=create_fixture(path,db)
            repo.create_session_proposition(conn,'session_A',{'id':'p','kind':'koerperkontakt',
                           'actorId':'alice','targetId':'bob','state':'open'},'usr_A')
            for i,(by,kind,scope,part,window) in enumerate((first,second),1):
                tt={'id':f'tt{i}','role':'avatar','authority':'avatar','speaker_id':by,
                    'present_ids':['alice','bob'],'hears_ids':['alice'],'sees_ids':['alice'],'turn':i}
                repo.append_session_turn_truth(conn,'session_A',tt,'usr_A')
                repo.append_session_fact(conn,'session_A',{'id':f'f{i}',
                    'kind':'lifecycle','event_kind':kind,'actorId':by,'targetId':'alice',
                    'sourceTurnId':f'tt{i}','propositionId':'p','turn':i,'validated':True,
                    'payload':{'koerperkontakt':{'scope':scope,'einschraenkung':part,
                                                  'window':window,'beleg':part or ''}}},'usr_A')
            conn.commit();conn.close()
            conn=sqlite3.connect(path);conn.row_factory=sqlite3.Row
            session=repo.get_session(conn,'usr_A','session_A')
            prop=next(x for x in session['propositions'] if x['id']=='p')
            if expected=='right_permission':
                actual=[x['einschraenkung'] for x in sc.restricted_permissions_standing(session,prop,at=at)]
                goal=['rechte Hand']
            elif expected=='right_refusal':
                actual=[x['einschraenkung'] for x in sc.restricted_refusals_standing(session,prop,at=at)]
                goal=['rechte Hand']
            else:
                actual=(sc.body_contact_standing(session,prop,at=at) or {}).get('state')
                goal=expected
            original_rows=conn.execute('SELECT COUNT(*) FROM scene_facts WHERE session_id=?',('session_A',)).fetchone()[0]
            unrelated=repo.get_session(conn,'usr_B','session_B')
            entry={'case':name,'required':goal,'original_actual':actual,'original_contract_pass':actual==goal,
                   'sqlite_facts_after_reopen':original_rows,
                   'unrelated_session_facts':len(unrelated.get('facts') or [])}
            out.append(entry)
            conn.close()
    report={'source':'UNCHANGED_V67', 'purpose':'reproduce existing bugs (not candidate proof)',
            'cases':out,'contract_failures':sum(not c['original_contract_pass'] for c in out),
            'rust_executed':False,'product_release':False}
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report['contract_failures']==len(out) else 1

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('original_root',type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    sys.exit(run(args.original_root,args.output))
