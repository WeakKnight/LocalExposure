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
