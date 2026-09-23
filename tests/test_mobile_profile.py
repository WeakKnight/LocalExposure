import unittest
from tools.profiling.mobile_profile import workload, spirv_stats, aoc_metrics, aoc_sections, compare


class MobileProfileTests(unittest.TestCase):
    def test_workload(self):
        w = workload(1920, 1080)
        self.assertEqual(w['low_size'], [480, 270])
        self.assertEqual(len(w['mip_sizes']), 9)
        self.assertEqual(len(w['dispatches']), 32)
        self.assertEqual(w['inverse_lut_bytes'], 2048)
        self.assertTrue(all(d['launched_threads'] >= d['useful_threads'] for d in w['dispatches']))

    def test_tiny_and_odd(self):
        self.assertEqual(workload(1, 1)['low_size'], [1, 1])
        self.assertEqual(workload(1921, 1081)['low_size'], [481, 271])
        with self.assertRaises(ValueError):
            workload(0, 1080)

    def test_ir_precision(self):
        s = spirv_stats('''; OpFAdd is only a comment
%h = OpTypeFloat 16
%v = OpTypeVector %h 4
%f = OpTypeFloat 32
%x = OpFMul %v %a %b
%y = OpExtInst %f %glsl Sqrt %c
%z = OpFConvert %h %y
OpLoopMerge %a %b None
''')
        self.assertEqual(s['float16_arithmetic_sites'], 1)
        self.assertEqual(s['float32_arithmetic_sites'], 1)
        self.assertEqual(s['loop_sites'], 1)
        self.assertNotIn('OpFAdd', s['opcodes'])

    def test_aoc_sections_and_missing(self):
        self.assertEqual(aoc_metrics('not installed'), {})
        s = aoc_metrics('Total instruction count: 15\nTotal instruction count: 20\nALU fiber occupancy percentage: 50.5%')
        self.assertEqual(s['Total instruction count'], [15, 20])
        self.assertEqual(s['ALU fiber occupancy percentage'], [50.5])

    def test_comparison_rejects_incompatible_target(self):
        baseline = dict(schema=1, config={'target':'a750'}, compiler={}, aoc=None, passes={})
        self.assertEqual(compare(baseline, baseline), {})
        with self.assertRaises(ValueError):
            compare(baseline, dict(baseline, config={'target':'a740'}))

    def test_aoc_section_identity(self):
        result = aoc_sections('Shader Preamble Stats\nTotal instruction count: 69\nMain Shader Stats\nTotal instruction count: 182\nPerformance Stats\nCycles with ALU instructions: 38.7 %')
        self.assertEqual(result['Shader Preamble Stats']['Total instruction count'], [69])
        self.assertEqual(result['Main Shader Stats']['Total instruction count'], [182])
        self.assertEqual(result['Performance Stats']['Cycles with ALU instructions'], [38.7])


if __name__ == '__main__':
    unittest.main()
