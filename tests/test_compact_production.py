"""The readable production stages must preserve the frozen optimized graph."""
import unittest
import numpy as np
import slangpy as spy
from tone_mapper import ROOT, ToneMapper, create_hdr_texture
from tests.compact_reference import ReferenceCandidate
from tools.profiling.android.quality_sweep import Candidate


class ProductionParityTests(unittest.TestCase):
    def test_production_matches_frozen_graph(self):
        device = spy.Device(enable_hot_reload=False)
        mapper = ToneMapper(device)
        pack = device.create_compute_kernel(device.create_slang_session().load_program(
            str(ROOT / 'tools/profiling/android/pack_source.slang'), ['pack_source']))
        for variant in ('guided-packed-coefficients', 'guided-coefficient-layout'):
            actual = Candidate(device, mapper, variant)
            control = ReferenceCandidate(device, mapper, variant)
            for w, h, ev, bracket, packed in [(4, 4, 0, 1.2, False),
                    (128, 64, -2, 3, True), (513, 289, 2, 3, False)]:
                with self.subTest(variant=variant, size=(w,h), ev=ev, packed=packed):
                    rng = np.random.default_rng(1221)
                    rgba = np.exp2(rng.uniform(-16, 14, (h,w,4))).astype(np.float32)
                    rgba[:, :w//2, :3] *= .001
                    rgba[::3, ::3, :3] = -1 if not packed else 0
                    rgba[...,3] = 1
                    source = create_hdr_texture(device, rgba)
                    if packed:
                        dst = mapper.create_texture(w,h,spy.Format.r11g11b10_float)
                        pack.dispatch(thread_count=[w,h,1],vars=dict(inputTexture=source,outputTexture=dst))
                        source = dst
                    encoder = device.create_command_encoder()
                    mapper.prepare_weights(encoder,source,ev,bracket,bracket,.2)
                    device.submit_command_buffer(encoder.finish())
                    expected = control.render(source,ev,bracket)
                    result = actual.render(source,ev,bracket)
                    for a,b in zip(result,expected):
                        self.assertTrue(np.isfinite(a).all())
                        np.testing.assert_array_equal(a,b)


if __name__ == '__main__':
    unittest.main()
