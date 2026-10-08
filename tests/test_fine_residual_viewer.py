"""The viewer must run the validated fine-residual graph, including odd sizes."""
import unittest
from unittest.mock import Mock
import numpy as np
import slangpy as spy

from fine_residual import FineResidualToneMapper
from main import Viewer, create_mapper, parse_args
from tone_mapper import ToneMapper, create_hdr_texture
from tools.profiling.controls.legacy_guided import LegacyGuidedToneMapper
from tools.profiling.android.quality_sweep import Candidate


class FineResidualViewerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.device = spy.Device(enable_hot_reload=False)
        cls.runtime = FineResidualToneMapper(cls.device)
        cls.control = LegacyGuidedToneMapper(cls.device)
        cls.control.curve = cls.runtime.curve
        cls.candidate = Candidate(cls.device, cls.control, 'fine-residual-lookup')

    def submit(self, mapper, source, ev, hi, sh, sigma, production=False):
        enc = self.device.create_command_encoder()
        mapper.prepare_weights(enc, source, ev, hi, sh, sigma)
        mapper.prepare_result(enc, source, ev, production=production)
        self.device.submit_command_buffer(enc.finish())
        return mapper.final_color.to_numpy()

    def test_matches_mobile_graph_and_debug_output(self):
        rng = np.random.default_rng(823)
        # Tiny/fallback, odd mixed mips, fused fine and fused tail schedules.
        for w, h in [(1, 1), (3, 2), (65, 1), (33, 35), (513, 289), (1920, 1080)]:
            rgba = np.exp2(rng.uniform(-12, 10, (h, w, 4))).astype(np.float32)
            source = create_hdr_texture(self.device, rgba)
            for ev, hi, sh, sigma in [(0, 2.856, 1.2, .2), (-2, 6, 0, .02), (2, 0, 6, .8)]:
                with self.subTest(size=(w, h), ev=ev, sigma=sigma):
                    actual = self.submit(self.runtime, source, ev, hi, sh, sigma)
                    self.submit(self.control, source, ev, hi, sh, sigma)
                    expected, _ = self.candidate.render(source, ev, sigma=sigma, highlight_ev=hi, shadow_ev=sh)
                    np.testing.assert_array_equal(actual, expected)
                    production = self.submit(self.runtime, source, ev, hi, sh, sigma, production=True)
                    np.testing.assert_array_equal(actual, production)
                    self.assertTrue(np.isfinite(self.runtime.local_exposure.to_numpy()).all())

    def test_cache_source_and_reload(self):
        for value in [.01, 20.]:
            source = create_hdr_texture(self.device, np.full((65, 67, 4), value, np.float32))
            before = self.submit(self.runtime, source, 0, 3, 1.2, .2)
            cached = self.submit(self.runtime, source, 0, 3, 1.2, .2)
            np.testing.assert_array_equal(before, cached)
            curve = self.runtime.curve
            self.runtime.reload()
            self.runtime.curve = curve
            after = self.submit(self.runtime, source, 0, 3, 1.2, .2)
            np.testing.assert_array_equal(before, after)

    def test_viewer_selects_and_switches_independent_graphs(self):
        viewer = Viewer.__new__(Viewer)
        viewer.device, viewer.args = self.device, parse_args([])
        viewer.mapper = create_mapper(self.device, viewer.args)
        viewer.status, viewer.resolution_selector = Mock(), Mock()
        self.assertIsInstance(viewer.mapper, FineResidualToneMapper)
        curve = viewer.mapper.curve
        viewer.set_resolution(1)
        self.assertIs(type(viewer.mapper), ToneMapper)
        self.assertEqual(viewer.mapper.fusion_scale, 1)
        viewer.set_resolution(0)
        self.assertIsInstance(viewer.mapper, FineResidualToneMapper)
        self.assertIs(viewer.mapper.curve, curve)

    def test_reference_cannot_select_removed_guided_path(self):
        with self.assertRaisesRegex(ValueError, 'full-resolution reference'):
            ToneMapper(self.device, fusion_scale=4)


if __name__ == '__main__':
    unittest.main()
