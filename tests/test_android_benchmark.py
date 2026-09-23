"""Production entry parity and benchmark result accounting."""
import unittest

import numpy as np
import slangpy as spy

from tone_mapper import ROOT, ToneMapper, create_hdr_texture
from tools.profiling.android.benchmark import stats, summarize, validate
from tools.profiling.android.bandwidth import bandwidth_stats
from tools.profiling.android.timer_audit import analyze


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

    def test_timer_audit_detects_wrong_units_and_out_of_domain_queries(self):
        import copy
        clock=lambda lo,hi: dict(available=True,samples=[dict(device_ticks=lo,host_ns=lo*50,max_deviation_ns=100),
                                                     dict(device_ticks=hi,host_ns=hi*50,max_deviation_ns=100)])
        cases=[dict(name=name,gpu_ms=[ms],cpu_ms=[ms+.2],ticks=[[2100,2200]]) for name,ms in
               [('timestamps_only',.002),('empty_32400_groups',.375),('empty_32400_groups_x16',6.)]]
        report=dict(cases=cases,timestamp_period_ns=50,calibrated_clock=clock(1000,2000),
                    calibrated_clock_after=clock(3000,4000))
        self.assertTrue(analyze(report,report)['verified'])
        bad=copy.deepcopy(report); bad['timestamp_period_ns']=50000
        self.assertFalse(analyze(report,bad)['verified'])
        bad=copy.deepcopy(report); bad['cases'][0]['ticks']=[[1,2]]
        self.assertFalse(analyze(report,bad)['verified'])

    def test_bandwidth_decimal_units_and_invalid_samples(self):
        result=bandwidth_stats(1920*1080*(4+4),[.25,.25])
        self.assertAlmostEqual(result['median_gbps'],66.3552)
        self.assertAlmostEqual(1920*1080*8*45/1e9,.746496)
        for payload,ms in [(0,[1]),(1,[0]),(1,[]),(1,[np.nan])]:
            with self.assertRaises(ValueError): bandwidth_stats(payload,ms)

    def test_srgb_reference_gate_accepts_one_step_rejects_two(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            manifest=dict(resources=[dict(name='exposure',format_name='r16_float',width=1,height=1,bpp=2,dump=True),
                                     dict(name='final',format_name='rgba8_srgb',width=1,height=1,bpp=4,dump=True)])
            for suffix in ('reference','device','phone-reference'):
                np.array([1],np.float16).tofile(root/f'exposure.{suffix}.bin')
                np.array([100,100,100,255],np.uint8).tofile(root/f'final.{suffix}.bin')
            np.array([101,100,100,255],np.uint8).tofile(root/'final.device.bin')
            self.assertTrue(validate(root,manifest)['passed'])
            np.array([102,100,100,255],np.uint8).tofile(root/'final.device.bin')
            self.assertFalse(validate(root,manifest)['passed'])


if __name__=='__main__':
    unittest.main()
