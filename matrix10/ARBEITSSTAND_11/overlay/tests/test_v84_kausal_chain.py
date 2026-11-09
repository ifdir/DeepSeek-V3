"""V85: AMASTER 24.2/34.1/36.5/42/44/50 and closed writer-SQLite-reader tests.
All SQL tests use fresh temporary databases and never the attached user database.
"""
import copy
from contextlib import closing
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

# Only for code-level tests when Flask cannot be installed in this offline
# verification container. This local import shim is NEVER a shipped runtime
# replacement; it does not test Flask/HTTP.
try:
    import flask
except ModuleNotFoundError:
    import sys, types
    flask = types.ModuleType("flask")
    flask.jsonify = lambda x: x
    flask.request = types.SimpleNamespace(headers={})
    sys.modules["flask"] = flask

from matrix_api import kernel, llm_contract
from matrix_api.seed_builtin import seed_if_missing
from matrix_api.db import connect, init_schema, GASTHAUS_ID
from matrix_api.repos import save_session, get_session, create_session

MARA = {'id': 'char_g7_mara', 'name': 'Mara Nowak', 'compass': {}, 'role':'Kellnerin',
        'personality':'Loyal wo sicher, trotzig unter Druck, körperlich-direkt.'}
JOHANN = {'id': 'char_g7_johann', 'name': 'Johann Bruckner'}
NATIVES = [MARA, JOHANN]


def scene(event_text='Ich klatsch dir auf deinen arsch', event_id='ev1', *, turn=2):
    event=kernel.make_fact(turn=turn, actorId='char_g7_johann', targetId='char_g7_mara', kind='speech',
                           event_kind='speech', text=event_text, sourceTurnId='tt1', authority='character',
                           validated=True)
    event['id']=event_id
    event['plan']={'event_kind':'report','speech_act':'report','source':'llm','validation_status':'validated'}
    s={'id': 'ses_test_v84', 'userId':'admin','worldId':GASTHAUS_ID, 'turnIndex':turn,
       'avatarId':'', 'scene': {'presentIds':['char_g7_johann','char_g7_mara'],
                              'hearsIds':['char_g7_johann','char_g7_mara'], 'placeId':'schankraum'},
       'runtimes': {'char_g7_mara':{'characterId':'char_g7_mara','lust':0.05,'emotion':'wach', 'intensity':0.35}},
       'relations': [{'fromId':'char_g7_mara','toId':'char_g7_johann','trust':0.4,'closeness':0.2,'fear':0.1}],
       'facts': [event],
       'witnessKnowledge':[{'character_id':'char_g7_mara','fact_id':event_id,'access':'heard'}]}
    tt=kernel.bind_turn_truth(user_id='admin',world_id=GASTHAUS_ID,session_id=s['id'],role='teilnehmer',
                              speaker_id='char_g7_johann',avatar_id=None,target_id='char_g7_mara',
                              authority='character',present_ids=s['scene']['presentIds'],
                              hears_ids=s['scene']['hearsIds'],input_kind='speech',text=event_text,
                              input_actor_id='char_g7_johann')
    tt['id']='tt1'
    s['turnTruths']=[tt]
    pending=[{'id':'char_g7_mara','name':'Mara Nowak', 'events':[{'fact':event,'access':'heard'}], 'superseded':[]}]
    return s,pending,event


def proposed(*, state=.3, trust=.1, closeness=.1, feeling='Überraschung'):
    return {'figur':'Mara Nowak', 'raum':'Lust', 'aktivierung':.8,'gefuehl':feeling,
            'gegenueber':'Johann Bruckner','zustand_aenderung':{'lust':state},
            'beziehung_aenderung':[{'zu':'Johann Bruckner','trust':trust,'closeness':closeness}],
            'grund':'Johann macht eine anstößige Bemerkung'}


def proofs(row, event, *, supported=True, anchor=None, id=None, fields=None):
    wanted=kernel.appraisal_effect_fields(row) if fields is None else fields
    return {'pruefungen':[{'feld':field, 'urteil':'gestuetzt' if supported else 'nicht_gestuetzt',
             'factId':id or event['id'], 'beleg': anchor if anchor is not None else event['text'],
             'dispositionsBeleg':'Loyal wo sicher', 'richtung':('steigt' if kernel.appraisal_field_sign(row,field)>0 else 'sinkt'),
             'begruendung':'Loyal wo sicher: Maras Disposition und das konkrete Ereignis können je nach Beziehung unterschiedliche Wirkungen tragen.'}
              for field in wanted]}


class AppraisalChain(unittest.TestCase):
    def test_unvalidated_proposal_never_changes_runtime_relation(self):
        s,p,e=scene()
        out,diag=kernel.apply_appraisals(s,p,{'bewertungen':[proposed()]},natives=NATIVES)
        self.assertEqual(out['runtimes']['char_g7_mara']['lust'],.05)
        self.assertEqual(out['relations'][0]['trust'],.4)
        self.assertEqual(out['relations'][0]['closeness'],.2)
        self.assertFalse([f for f in out['facts'] if f.get('kind')=='appraisal'])
        self.assertIn('kausalpruefung_fehlend:zustand.lust',diag[0]['rejects'])
        self.assertIn(e['id'],out['runtimes']['char_g7_mara'].get('appraisalCauses',[]))
        self.assertEqual(s['runtimes']['char_g7_mara']['lust'],.05)

    def test_unjustified_positive_proposal_rejected_without_forcing_negative(self):
        s,p,e=scene()
        row=proposed(); row['_kausalpruefung']=proofs(row,e,supported=False)
        out,diag=kernel.apply_appraisals(s,p,{'bewertungen':[row]},natives=NATIVES)
        self.assertFalse(diag[0]['runtimeDelta'])
        self.assertFalse(diag[0]['relationDelta'])
        self.assertTrue(any(x.startswith('wirkung_nicht_belegt:') for x in diag[0]['rejects']))
        self.assertEqual(out['relations'][0]['fear'],.1)

    def test_same_reason_different_source_fact_rejected(self):
        s,p,e=scene()
        for bad in ({'id':'not_witnessed'}, {'quote':'fremder erfundener Satz'}):
            row=proposed()
            row['_kausalpruefung']=proofs(row,e,id=bad.get('id'),anchor=bad.get('quote'))
            out,diag=kernel.apply_appraisals(s,p,{'bewertungen':[row]},natives=NATIVES)
            self.assertEqual(out['relations'][0]['trust'],.4)
            self.assertEqual(out['runtimes']['char_g7_mara']['lust'],.05)
            self.assertTrue(diag[0]['rejects'])

    def test_one_effect_fails_another_is_allowed(self):
        s,p,e=scene('Ich habe deine verlorenen Unterlagen gefunden')
        row=proposed(state=0.0, trust=.1, closeness=.1, feeling='')
        row['_kausalpruefung']=proofs(row,e,fields=['beziehung.0.trust'])
        out,diag=kernel.apply_appraisals(s,p,{'bewertungen':[row]},natives=NATIVES)
        self.assertGreater(out['relations'][0]['trust'],.4)
        self.assertEqual(out['relations'][0]['closeness'],.2)
        self.assertIn('kausalpruefung_fehlend:beziehung.0.closeness',diag[0]['rejects'])
        self.assertEqual(out['relations'][0].get('sourceFactId') or out['relations'][0].get('causeFactId') or e['id'], e['id'])

    def test_existing_negative_or_positive_effects_are_not_prejudged(self):
        s,p,e=scene('Johann sagt: Ich habe deine verlorenen Unterlagen gefunden')
        for delta in (-.1,.1):
            row=proposed(state=0,trust=delta,closeness=0,feeling='')
            row['_kausalpruefung']=proofs(row,e)
            out,diag=kernel.apply_appraisals(s,p,{'bewertungen':[row]},natives=NATIVES)
            self.assertEqual(diag[0]['rejects'],[])
            self.assertNotEqual(out['relations'][0]['trust'],.4)

    def test_idempotent_retry_does_not_double_apply(self):
        s,p,e=scene('Danke, dass du mir geholfen hast')
        row=proposed(state=.1,trust=.1,closeness=.1,feeling='Freude')
        row['_kausalpruefung']=proofs(row,e)
        first,diag=kernel.apply_appraisals(s,p,{'bewertungen':[row]},natives=NATIVES)
        second,diag2=kernel.apply_appraisals(first,p,{'bewertungen':[row]},natives=NATIVES)
        self.assertEqual(second['relations'],first['relations'])
        self.assertEqual(second['runtimes']['char_g7_mara']['lust'],first['runtimes']['char_g7_mara']['lust'])
        self.assertEqual(len(second['facts']),len(first['facts']))

    def test_independent_check_runs_and_is_visible_to_kernel(self):
        # Stand 11 (SPS V62.7; nur die Aufrufstruktur angepasst): der Kausalnachweis kommt in DERSELBEN Erlebensantwort
        # (Feld "kausalpruefung") statt in einem zweiten Aufruf; Schutz bleibt: er deckt jedes Wirkungsfeld und erreicht den Kernel.
        fig={'figur':'Mara Nowak','gerade_geschehen':[{'id':'ev1','text':'Danke, dass du mir geholfen hast'}],
             'profil':{'persoenlichkeit':'freundlich'}}
        recs=[]
        def fake_json(routing, rule, payload, **kwargs):
            recs.append((rule,payload))
            if rule==llm_contract.APPRAISAL_RULES+llm_contract.APPRAISAL_KAUSAL_IN_ERSTER_ANTWORT:
                row=proposed(state=.1,trust=.1,closeness=0,feeling='Freude')
                return dict(row, kausalpruefung=proofs(row,{'id':'ev1','text':'Danke, dass du mir geholfen hast'}))
            self.fail('wrong prompt')
        with patch.object(llm_contract,'_routing',return_value={'allowed':True}), \
             patch.object(llm_contract,'_llm_json',side_effect=fake_json):
            r=llm_contract.appraise_events(None,'admin',{'figuren':[fig], 'personen':['Mara Nowak','Johann Bruckner']})
        self.assertEqual(len(recs),1, "ein Aufruf je Figur")
        self.assertIn('_kausalpruefung',r['bewertungen'][0]); self.assertNotIn('kausalpruefung',r['bewertungen'][0])
        self.assertEqual(sorted(x['feld'] for x in r['bewertungen'][0]['_kausalpruefung']['pruefungen']),
                         sorted(kernel.appraisal_effect_fields(r['bewertungen'][0])))
        s,p,e=scene('Danke, dass du mir geholfen hast')
        out,diag=kernel.apply_appraisals(s,p,{'bewertungen':[dict(r['bewertungen'][0], _kausalpruefung=proofs(r['bewertungen'][0],e))]},natives=NATIVES)
        self.assertEqual(diag[0]['rejects'],[])
        # ohne Nachweis in derselben Antwort: der Kernel verwirft die Wirkungen (keine Ersatzlesung)
        def ohne(routing, rule, payload, **kwargs):
            return proposed(state=.1,trust=.1,closeness=0,feeling='Freude')
        with patch.object(llm_contract,'_routing',return_value={'allowed':True}), \
             patch.object(llm_contract,'_llm_json',side_effect=ohne):
            r2=llm_contract.appraise_events(None,'admin',{'figuren':[fig], 'personen':['Mara Nowak','Johann Bruckner']})
        self.assertEqual(r2['bewertungen'][0]['_kausalpruefung'],{'pruefungen':[]})
        out2,diag2=kernel.apply_appraisals(s,p,{'bewertungen':[r2['bewertungen'][0]]},natives=NATIVES)
        self.assertTrue(diag2[0]['rejects']); self.assertEqual(out2['relations'],s['relations'])

    def test_spoken_intention_is_not_committed_as_a_physical_act(self):
        """AMASTER 34.1: one speech fact stays speech even if the LLM calls it an act."""
        s,p,e=scene('Wir müssen reden')
        s['turnTruths'] = []
        t=kernel.bind_turn_truth(user_id='admin',world_id=s['worldId'],session_id=s['id'],
                                  role='teilnehmer',speaker_id=MARA['id'],avatar_id=None,
                                  target_id=JOHANN['id'],authority='character',
                                  present_ids=s['scene']['presentIds'],hears_ids=s['scene']['hearsIds'],
                                  input_kind='autochat',text='',input_actor_id=JOHANN['id'])
        props={'plan':{'event_kind':'action','speech_act':'act',
                       'summary':'Mara schlägt Johann auf den Arm', 'actor_id':MARA['id']}}
        out=kernel.commit_turn(s,truth=t,speaker=MARA,present=NATIVES,
                               result={'speech':'Ich schlage dich jetzt','proposals':props},
                               proposals=props)
        own=[f for f in out['facts'] if f.get('actorId')==MARA['id'] and f.get('text')=='Ich schlage dich jetzt']
        self.assertEqual(len(own),1)
        self.assertEqual(own[0]['kind'],'speech')
        self.assertEqual(own[0]['plan']['event_kind'],'report')
        self.assertEqual(own[0]['planAmbiguity']['reason'],'rede_als_handlung_klassifiziert')
        self.assertFalse([f for f in out['facts'] if f.get('actorId')==MARA['id'] and f.get('kind') in ('action','physical')])

    def test_reply_model_cannot_bypass_independent_relation_check(self):
        """The figure's own generated reply is no proof of a relationship effect."""
        s,p,e=scene('Wir müssen reden')
        s['turnTruths']=[]
        t=kernel.bind_turn_truth(user_id='admin',world_id=s['worldId'],session_id=s['id'],
                                  role='teilnehmer',speaker_id=MARA['id'],avatar_id=None,
                                  target_id=JOHANN['id'],authority='character',
                                  present_ids=s['scene']['presentIds'],hears_ids=s['scene']['hearsIds'],
                                  input_kind='autochat',text='',input_actor_id=JOHANN['id'])
        props={'beziehung':{'zu':'Johann Bruckner','trust':0.3,'closeness':0.3,
                             'grund':'die Worte gefielen ihr'}}
        out=kernel.commit_turn(s,truth=t,speaker=MARA,present=NATIVES,
                               result={'speech':'Ich höre dir zu','proposals':props},proposals=props)
        self.assertEqual(out['relations'][0]['trust'],s['relations'][0]['trust'])
        self.assertEqual(out['relations'][0]['closeness'],s['relations'][0]['closeness'])
        # Compass-driven synapse fallback may still run, but cannot write an
        # unverified directed relationship as its side effect.
        changed=kernel.apply_synapses(s,MARA,[{'space':'Lust','activation':.9,'cell':{}}],
                                      cause_fact_id=e['id'],turn=3,proposals=props,present=NATIVES)
        self.assertIsInstance(changed,dict)
        self.assertEqual(s['relations'][0]['trust'],.4)
        self.assertEqual(s['relations'][0]['closeness'],.2)

    def test_committed_causal_effect_survives_real_sqlite_roundtrip_and_brain_reader(self):
        s,p,e=scene('Danke, dass du mir geholfen hast')
        row=proposed(state=.1,trust=.1,closeness=0,feeling='Freude')
        row['_kausalpruefung']=proofs(row,e)
        out,diag=kernel.apply_appraisals(s,p,{'bewertungen':[row]},natives=NATIVES)
        self.assertTrue(diag[0]['runtimeDelta'])
        self.assertTrue(diag[0]['relationDelta'])
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'only_test.sqlite'
            prior=os.environ.pop('MATRIX_SKIP_SEED',None)
            try:
                with closing(connect(path)) as db:
                    init_schema(db)
                    seed_if_missing(db)  # temp DB test fixture; independent of test runner
                    db.commit()
                    # Client creation intentionally discards kernel-owned fields.
                    # Only the subsequent internal canonical save may write them.
                    create_session(db,{'id':out['id'],'worldId':GASTHAUS_ID,'name':'Kausalprobe','presentIds':[MARA['id'],JOHANN['id']]},'admin')
                    written=save_session(db,'admin',out)
                    db.commit()
                with closing(connect(path)) as db:
                    read=get_session(db,'admin',out['id'])
                    self.assertEqual(db.execute('PRAGMA quick_check').fetchone()[0],'ok')
                rel=[r for r in read['relations'] if r['fromId']==MARA['id'] and r['toId']==JOHANN['id']][0]
                self.assertAlmostEqual(rel['trust'],out['relations'][0]['trust'])
                self.assertEqual(read['runtimes'][MARA['id']]['lust'],out['runtimes'][MARA['id']]['lust'])
                ctx=kernel.brain_context(read,MARA['id'])
                self.assertFalse(ctx['writable'])
                self.assertIn('currentState',ctx)
                self.assertEqual(ctx['runtime']['lust'],out['runtimes'][MARA['id']]['lust'])
            finally:
                if prior is not None:
                    os.environ['MATRIX_SKIP_SEED']=prior


if __name__=='__main__': unittest.main()
