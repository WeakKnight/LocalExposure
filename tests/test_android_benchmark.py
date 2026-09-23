"""Production entry parity and benchmark result accounting."""
import unittest

import numpy as np
import slangpy as spy

from tone_mapper import ROOT, ToneMapper, create_hdr_texture
from tools.profiling.android.benchmark import stats, summarize


class AndroidBenchmarkTests(unittest.TestCase):
    def test_production_entry_matches_viewer_without_debug_resources(self):
        device=spy.Device(enable_hot_reload=False)
        mapper=ToneMapper(device)
        session=device.create_slang_session(compiler_options={'include_paths':[ROOT/'shaders']})
        kernel=device.create_compute_kernel(session.load_program('guided.slang',['apply_exposure_production']))
        rng=np.random.default_rng(671)
        for h,w in [(1,1),(17,31),(108,192)]:
            rgba=np.exp2(rng.uniform(-16,15,(h,w,4))).astype(np.float32)
            rgba[0,0,:3]=0
            source=create_hdr_texture(device,rgba)
            enc=device.create_command_encoder()
            mapper.prepare_weights(enc,source,-1.25,1.2,1.2)
            mapper.prepare_result(enc,source,-1.25)
            actual=mapper.create_texture(w,h,spy.Format.rgba16_float)
            kernel.dispatch(thread_count=[w,h,1],vars=dict(fullSource=source,
                lowExposure=mapper.low_exposure,averagedCoefficients=mapper.averaged_coefficients,
                linearSampler=mapper.sampler,globalEV=-1.25,guided=True,colorOutput=actual),command_encoder=enc)
            device.submit_command_buffer(enc.finish())
            # Separate entry points can change backend scheduling/contraction.
            # Permit at most one representable FP16 step on desktop; the phone
            # benchmark independently records strict bitwise same-device parity.
            a=actual.to_numpy(); b=mapper.final_color.to_numpy()
            self.assertTrue(np.isfinite(a).all() and np.isfinite(b).all())
            self.assertTrue((a>=0).all() and (b>=0).all())
            ulps=abs(a.view(np.uint16).astype(np.int32)-b.view(np.uint16).astype(np.int32))
            self.assertLessEqual(ulps.max(),1)

    def test_separate_diagnostic_from_whole_chain(self):
        raw=dict(blocks=[dict(kind='fusion',round=0,gpu_ms=[1,2,3]),
                         dict(kind='baseline',round=0,gpu_ms=[.2,.3,.4])],
                 passes=['a','b'],diagnostic_ms=[[10,4,5],[12,5,6]])
        s=summarize(raw)
        self.assertEqual(s['totals']['fusion']['median'],2)
        self.assertEqual(s['per_pass']['a']['median'],4.5)
        self.assertAlmostEqual(s['median_difference_ms'],1.7)
        for values in [[],[float('nan')],[float('inf')],[0],[-1]]:
            with self.assertRaises(ValueError):
                stats(values)


if __name__=='__main__':
    unittest.main()
