"""Independent V87 constraints: a model's asserted causal classification is
not the source for an effect. A second quote must resolve to the target's
canonical disposition, not to another figure or an invented profile.
"""
import unittest
from unittest.mock import patch
import json
from pathlib import Path
import test_v84_kausal_chain  # existing offline Flask-test import environment
from test_v84_kausal_chain import scene, proposed
from matrix_api import kernel, llm_contract

ROOT = Path(__file__).resolve().parents[1]
S = json.loads((ROOT/'matrix_api/gasthaus_seed.json').read_text(encoding='utf-8'))
MARA = next(c for c in S['characters'] if c['id']=='char_g7_mara')
JOHANN = next(c for c in S['characters'] if c['id']=='char_g7_johann')
NATIVES = [MARA,JOHANN]


def reviewed(row, event, *, quote='Loyal wo sicher', reason=None, verdict='gestuetzt'):
    reason = reason or f'{quote}: Das konkrete Ereignis wird durch die Bindung und ihre Disposition gedeutet.'
    return {'pruefungen':[{'feld':field, 'urteil':verdict, 'factId':event['id'],
                          'beleg':event['text'], 'dispositionsBeleg':quote, 'richtung':('steigt' if kernel.appraisal_field_sign(row,field)>0 else 'sinkt'),
                          'begruendung':reason} for field in kernel.appraisal_effect_fields(row)]}


class SourceGrounding(unittest.TestCase):
    def test_generic_positive_does_not_write_any_effect(self):
        s,p,e=scene('Ich klatsch dir auf deinen arsch')
        row=proposed(feeling='Begeisterung', state=.3, trust=.1, closeness=.1)
        row['_kausalpruefung']=reviewed(row,e,quote='',reason='Ich habe den Sachverhalt relativ zum Profil interpretiert.')
        result,protocol=kernel.apply_appraisals(s,p,{'bewertungen':[row]},natives=NATIVES)
        self.assertEqual(result['relations'],s['relations'])
        self.assertEqual(result['runtimes'][MARA['id']]['lust'],.05)
        self.assertFalse([f for f in result['facts'] if f.get('kind')=='appraisal'])
        self.assertTrue(any('disposition_nicht_belegt:' in item for item in protocol[0]['rejects']))
        self.assertNotIn(e['id'],result['runtimes'][MARA['id']].get('appraisedFactIds',[]))

    def test_truthful_event_citation_plus_fake_personality_still_rejected(self):
        s,p,e=scene('Danke für deine Hilfe')
        row=proposed(feeling='',state=0,trust=.1,closeness=0)
        row['_kausalpruefung']=reviewed(row,e,quote='Mara genießt jede Demütigung')
        result,protocol=kernel.apply_appraisals(s,p,{'bewertungen':[row]},natives=NATIVES)
        self.assertEqual(result['relations'],s['relations'])
        self.assertIn('disposition_nicht_belegt:beziehung.0.trust',protocol[0]['rejects'])

    def test_real_quote_of_another_figure_not_accepted_for_mara(self):
        s,p,e=scene('Danke für deine Hilfe')
        row=proposed(feeling='',state=0,trust=.1,closeness=0)
        row['_kausalpruefung']=reviewed(row,e,quote='verspielte Neugier und grenzenloses Vertrauen')
        # Even if the other figure had such a trait, it is not Mara's truth.
        other={**JOHANN,'personality':'verspielte Neugier und grenzenloses Vertrauen'}
        result,protocol=kernel.apply_appraisals(s,p,{'bewertungen':[row]},natives=[MARA,other])
        self.assertEqual(result['relations'],s['relations'])
        self.assertIn('disposition_nicht_belegt:beziehung.0.trust',protocol[0]['rejects'])

    def test_a_quote_must_appear_in_reason_as_well_as_real_profile(self):
        s,p,e=scene('Danke für deine Hilfe')
        row=proposed(feeling='',state=0,trust=.1,closeness=0)
        row['_kausalpruefung']=reviewed(row,e,quote='Loyal wo sicher',reason='Der Bote wirkt vertrauenswürdig.')
        result,protocol=kernel.apply_appraisals(s,p,{'bewertungen':[row]},natives=NATIVES)
        self.assertEqual(result['relations'],s['relations'])
        self.assertIn('disposition_nicht_belegt:beziehung.0.trust',protocol[0]['rejects'])

    def test_grounded_support_can_go_either_direction_without_a_character_rule(self):
        for delta in (.1,-.1):
            s,p,e=scene('Johann bietet ihr Hilfe an')
            row=proposed(feeling='',state=0,trust=delta,closeness=0)
            row['_kausalpruefung']=reviewed(row,e,quote='Loyal wo sicher')
            result,protocol=kernel.apply_appraisals(s,p,{'bewertungen':[row]},natives=NATIVES)
            self.assertFalse(protocol[0]['rejects'],protocol)
            self.assertNotEqual(result['relations'][0]['trust'],s['relations'][0]['trust'])

    def test_causal_check_budget_scales_with_effects_without_new_provider_calls(self):
        fig={'figur':'Mara Nowak', 'profil':{'persoenlichkeit':'Loyal wo sicher'},
             'gerade_geschehen':[{'id':'evt','text':'Hilfe in der Gaststube'}]}
        proposal={'figur':'Mara Nowak','gefuehl':'Freude','absicht':'Danke sagen',
                  'zustand_aenderung':{'angst':.1,'wut':-.1,'scham':.1,'stress':.1,'lust':.1},
                  'beziehung_aenderung':[{'zu':'Johann Bruckner','trust':.1,'closeness':.1,'fear':.1}]}
        fields=kernel.appraisal_effect_fields(proposal)
        self.assertGreaterEqual(len(fields),9)
        calls=[]
        def fake_json(routing,system,payload,**kw):
            calls.append((system,kw))
            if system==llm_contract.APPRAISAL_RULES+llm_contract.APPRAISAL_KAUSAL_IN_ERSTER_ANTWORT:
                return dict(proposal, kausalpruefung={'pruefungen':[]})
            return None
        with patch.object(llm_contract,'_routing',return_value={'allowed':True}),patch.object(llm_contract,'_llm_json',side_effect=fake_json):
            llm_contract.appraise_events(None,'admin',{'figuren':[fig], 'personen':['Mara Nowak','Johann Bruckner']})
        # Stand 11 (nur Aufrufstruktur): EIN Aufruf; sein Antwortraum fasst das Erleben (320) UND den vollen Kausalnachweis
        # je Wirkungsfeld (frueher eigener Aufruf mit min(3200, 160 je Feld + 200))
        self.assertEqual(len(calls),1)
        self.assertGreaterEqual(calls[0][1]['max_tokens'],320+min(3200,160*len(fields)+200))
        self.assertLessEqual(calls[0][1]['max_tokens'],320+3200)

if __name__=='__main__':unittest.main()

class ApprovedProfileOnly(unittest.TestCase):
    def test_unapproved_session_learning_cannot_become_stable_personality_proof(self):
        s, p, e = scene('Johann stoest Mara an')
        fabricated = 'Mara freut sich über jede verletzende Berührung'
        c = {**MARA, 'likes':[fabricated], 'learnedItems':[
            {'field':'likes','value':fabricated,'scope':'session','status':'pending',
             'sessionId':s['id']}]}
        row = proposed(feeling='',state=0,trust=.1,closeness=0)
        row['_kausalpruefung']=reviewed(row,e,quote=fabricated)
        out,protocol=kernel.apply_appraisals(s,p,{'bewertungen':[row]},natives=[c,JOHANN])
        self.assertEqual(out['relations'],s['relations'])
        self.assertIn('disposition_nicht_belegt:beziehung.0.trust',protocol[0]['rejects'])
        self.assertNotIn(fabricated,kernel.appraisal_disposition_sources(s,c,MARA['id'],{JOHANN['id']}))

class ShortExistingProfile(unittest.TestCase):
    def test_single_word_authored_personality_may_be_cited_in_full(self):
        s,p,e = scene('Johann hilft Mara')
        c={**MARA,'personality':'Loyal','relations':[], 'compass':{}}
        row=proposed(feeling='',state=0,trust=.1,closeness=0)
        row['_kausalpruefung']=reviewed(row,e,quote='Loyal',reason='Loyal: ein konkreter Hilfeakt ist für Mara ein Grund, Vertrauen aufzubauen.')
        out,protocol=kernel.apply_appraisals(s,p,{'bewertungen':[row]},natives=[c,JOHANN])
        self.assertFalse(protocol[0]['rejects'],protocol)
        self.assertGreater(out['relations'][0]['trust'],s['relations'][0]['trust'])

    def test_truncated_single_word_is_not_a_disposition_citation(self):
        s,p,e = scene('Johann hilft Mara')
        c={**MARA,'personality':'Loyalität und aufrichtige Freundschaft'}
        row=proposed(feeling='',state=0,trust=.1,closeness=0)
        row['_kausalpruefung']=reviewed(row,e,quote='Loyalität')
        out,protocol=kernel.apply_appraisals(s,p,{'bewertungen':[row]},natives=[c,JOHANN])
        self.assertEqual(out['relations'],s['relations'])
        self.assertIn('disposition_nicht_belegt:beziehung.0.trust',protocol[0]['rejects'])
