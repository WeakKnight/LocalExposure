import copy
import json
import unittest
from pathlib import Path
from tools.profiling.android.traffic import estimate

class TrafficTests(unittest.TestCase):
    def setUp(self):
        self.manifest=json.loads(Path('docs/performance/baselines/adreno830-game-formats.json').read_text())['manifest']

    def test_baseline_formats_cancel_from_local_increment(self):
        original=estimate(self.manifest)
        changed=copy.deepcopy(self.manifest)
        for r in changed['resources']:
            if r['name'] in ('final','baseline'): r['bpp']=8
        result=estimate(changed)
        self.assertEqual(result['incremental_sweep_bytes'],original['incremental_sweep_bytes'])
        self.assertEqual(result['baseline_bytes']-original['baseline_bytes'],1920*1080*4)
        self.assertEqual(original['incremental_sweep_gbps'],original['incremental_sweep_bytes']*45/1e9)

    def test_current_guided_tile_halos_and_final_increment(self):
        rows={r['pass_name']:r for r in estimate(self.manifest)['rows']}
        self.assertEqual(rows['fit_coefficients']['expanded_read_bytes'],60*34*144*(16+2))
        self.assertEqual(rows['apply_exposure_production']['write_bytes'],0)
        self.assertEqual(rows['apply_exposure_production']['read_sweep_bytes'],480*270*8)
        self.assertEqual(rows['reconstruct_mip8']['read_sweep_bytes'],32)

    def test_unknown_pass_fails_instead_of_silently_undercounting(self):
        self.manifest['passes'][0]['entry']='future_pass'
        with self.assertRaises(ValueError): estimate(self.manifest)

    def test_direct_moments_counts_repeated_loads_but_same_resource_sweep(self):
        m=copy.deepcopy(self.manifest)
        m['resources'] += [dict(name='guide_ev',width=17,height=17,levels=1,bpp=8),
                           dict(name='averaged_test',width=17,height=17,levels=1,bpp=4)]
        m['config']['variant_settings']=dict(precomputed_ev=True,guided_vertical=2,guided_threads_y=16)
        m['passes']=[dict(entry='reconstruct_guided',label='guided',baseline=False,
            width=17,height=17,group_size=[16,16,1],descriptors=[
                dict(name='compactSource',resource='guide_ev',mip=0),
                dict(name='averagedOutput',resource='averaged_test',mip=0)])]
        before=estimate(m)['rows'][0]
        m['config']['variant_settings']['guided_direct_moments']=True
        after=estimate(m)['rows'][0]
        self.assertEqual(before['expanded_read_bytes'],4*24*24*8)
        self.assertEqual(after['expanded_read_bytes'],4*(10*24*6+256)*8)
        self.assertEqual(after['read_sweep_bytes'],before['read_sweep_bytes'])

        m['config']['variant_settings'].update(direct_batch=1,guided_threads_y=32)
        m['passes'][0]['group_size']=[16,32,1]
        single=estimate(m)['rows'][0]
        self.assertEqual(single['expanded_read_bytes'],4*(20*24*5+512)*8)
        self.assertEqual(single['read_sweep_bytes'],before['read_sweep_bytes'])
