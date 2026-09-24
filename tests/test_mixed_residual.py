"""Splitting storage must preserve the logical pyramid and independent reference."""
import copy
import unittest
from tools.profiling.android.prepare import split_residual_pyramid
from tools.profiling.android.traffic import estimate


class MixedResidualTests(unittest.TestCase):
    def test_traffic_counts_reads_across_format_boundary(self):
        m = dict(width=1920, height=1080, config={}, resources=[
            dict(name=n, width=480, height=270, levels=9, bpp=4, format_name='rg16_float')
            for n in ['luminance', 'reconstructed', 'weights', 'baseline', 'source']],
            passes=[dict(entry='reconstruct_compact', label='mip3', baseline=False,
                         width=60, height=33, descriptors=[
                dict(name=k, resource=r, mip=i) for k, r, i in [
                    ('fineLuminance', 'luminance', 3), ('coarseLuminance', 'luminance', 4),
                    ('layerWeights', 'weights', 3), ('previousResult', 'reconstructed', 4),
                    ('reconstructionOutput', 'reconstructed', 3)]])])
        before = estimate(m)['incremental_sweep_bytes']
        split_residual_pyramid(m, 4)
        after = estimate(m)['incremental_sweep_bytes']
        self.assertEqual(after - before, 30 * 16 * 4)

    def test_every_binding_keeps_its_extent_and_all_levels(self):
        cases = [(w, h, levels, split) for w, h, levels in
                 [(480, 270, 9), (129, 73, 8), (3, 1, 2)] for split in (3, 4)]
        for width, height, levels, split in cases:
            with self.subTest(size=(width, height), split=split):
                resource = dict(name='luminance', width=width, height=height, levels=levels,
                                format=83, format_name='rg16_float', bpp=4, dump=True)
                m = dict(resources=[resource], passes=[dict(descriptors=[
                    dict(resource='luminance', mip=i) for i in range(levels)])],
                    reference_resources=[copy.deepcopy(resource)])
                original = copy.deepcopy(m)
                split_residual_pyramid(m, split)
                self.assertEqual(m['reference_resources'], original['reference_resources'])
                self.assertEqual(len(m['passes']), len(original['passes']))
                resources = {r['name']: r for r in m['resources']}
                for i, binding in enumerate(m['passes'][0]['descriptors']):
                    r, mip = resources[binding['resource']], binding['mip']
                    self.assertLess(mip, r['levels'])
                    self.assertEqual((max(1, r['width'] >> mip), max(1, r['height'] >> mip)),
                                     (max(1, width >> i), max(1, height >> i)))
                self.assertEqual(sum(r['levels'] for r in resources.values()), levels)
                if levels <= split:
                    self.assertEqual(m, original)


if __name__ == '__main__':
    unittest.main()
