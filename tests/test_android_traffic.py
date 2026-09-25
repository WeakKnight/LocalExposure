import copy
import json
import unittest
from pathlib import Path
from tools.profiling.android.traffic import estimate

class TrafficTests(unittest.TestCase):
    def setUp(self):
        self.manifest=json.loads((Path(__file__).parent/'fixtures/android-traffic-manifest.json').read_text())

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

    def test_fused_reconstruction_counts_halos_and_deduplicates_bound_mips(self):
        m=copy.deepcopy(self.manifest)
        m['resources']=[dict(name=name,width=32,height=32,levels=6,bpp=4)
                        for name in ('luminance','weights','recon','compact','base','guide','source','baseline')]
        m['resources'].append(dict(name='inverse',width=1024,height=1,levels=1,bpp=2,one_d=True))
        bindings={'fineLuminance':('luminance',0),'coarseLuminance':('luminance',1),
                  'mip2Luminance':('luminance',2),'mip3Luminance':('luminance',3),
                  'layerWeights':('weights',0),'mip1Weights':('weights',1),'mip2Weights':('weights',2),
                  'previousResult':('recon',3),'compactSource':('compact',0),
                  'baseLightness':('base',0),'compactOutput':('guide',0),'inverseLut':('inverse',0)}
        m['passes']=[dict(entry='reconstruct_ev_fused',label='fused',width=32,height=32,
            baseline=False,descriptors=[dict(name=k,resource=v[0],mip=v[1]) for k,v in bindings.items()])]
        row=estimate(m)['rows'][0]
        self.assertEqual(row['write_bytes'],32*32*4)
        self.assertEqual(row['read_sweep_bytes'],(1024+256+64+16)*4+(1024+256+64)*4+16*4+2*1024*4+2048)
        self.assertEqual(row['expanded_read_bytes'],4*49*(4+16+4+16)+4*100*(4+16+4)+1024*(4+16+4+4+4+4))

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

        m['config']['variant_settings'].update(guided_gather_rows=True,guided_threads_y=16)
        m['passes'][0]['group_size']=[16,16,1]
        gather=estimate(m)['rows'][0]
        self.assertEqual(gather['expanded_read_bytes'],4*(20*12*(4*4+2)+256)*8)
        self.assertEqual(gather['read_sweep_bytes'],before['read_sweep_bytes'])
        self.assertEqual(gather['write_bytes'],before['write_bytes'])

        m['config']['variant_settings'].update(guided_direct_fit=True,tile_x=16,guided_threads_y=8)
        m['passes'][0]['group_size']=[8,8,1]
        direct=estimate(m)['rows'][0]
        self.assertEqual(direct['expanded_read_bytes'],4*(20*20*25+64)*8)
        self.assertEqual(direct['read_sweep_bytes'],before['read_sweep_bytes'])
        self.assertEqual(direct['write_bytes'],before['write_bytes'])
