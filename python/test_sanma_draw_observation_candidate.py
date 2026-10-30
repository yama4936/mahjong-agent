import copy
import unittest
from auto_operator import sanma_draw_observation_candidate

class SanmaDrawCandidateTests(unittest.TestCase):
    def sample(self):
        tiles=['1m','9m','9m','4p','0p','5p','6p','8p','2s','6s','S','S','N','E']
        geometry={'handSlots':[{'x':223+i*94,'y':921,'width':92,'height':151} for i in range(13)], 'drawSlot':{'x':1486,'y':921,'width':92,'height':151},
                  'clickPoints':[{} for _ in range(13)]+[{'x':1532,'y':990}]}
        return {'operationAuthorized':False, 'digest':'a'*64,
                'report':{'digest':'a'*64, 'hand':{'status':'candidate','value':{'tiles':tiles}},
                          'handGeometry':{'status':'candidate','value':geometry}}}

    def test_draw_is_only_an_unverified_physical_candidate(self):
        result=sanma_draw_observation_candidate(self.sample())
        self.assertEqual((result['status'],result['index'],result['tile']),('candidate',13,'E'))
        self.assertFalse(result['verified'])
        self.assertFalse(result['operationAuthorized'])

    def test_unknown_or_contradictory_data_never_produces_target(self):
        for change in ('digest','impossible_tile','too_many_copies','missing_hand','point','slot','overlap','false_authorization'):
            data=copy.deepcopy(self.sample())
            if change=='digest': data['report']['digest']='b'*64
            elif change=='impossible_tile': data['report']['hand']['value']['tiles'][0]='2m'
            elif change=='too_many_copies': data['report']['hand']['value']['tiles'][:5]=['5p','0p','5p','5p','5p']
            elif change=='missing_hand': data['report']['hand']={'status':'unresolved'}
            elif change=='point': data['report']['handGeometry']['value']['clickPoints'][-1]={'x':0,'y':0}
            elif change=='slot': data['report']['handGeometry']['value']['handSlots'].pop()
            elif change=='overlap': data['report']['handGeometry']['value']['handSlots'][-1]['x']=1480
            else: data['operationAuthorized']=True
            with self.subTest(change=change):
                result=sanma_draw_observation_candidate(data)
                self.assertEqual(result['status'],'unresolved')
                self.assertFalse(result['operationAuthorized'])
                self.assertNotIn('point',result)
