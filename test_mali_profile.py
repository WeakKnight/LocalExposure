import copy
import json
from pathlib import Path
import unittest
from tools.mali_profile import summarize, compare


class MaliTests(unittest.TestCase):
    def setUp(self):
        self.raw = json.loads((Path(__file__).parent/'docs/baselines/mali-fit-fixture.json').read_text())

    def test_real_report(self):
        result = summarize(self.raw, 'Immortalis-G720')
        v = result['variants'][0]
        self.assertEqual(v['properties']['work_registers_used'], 56)
        self.assertEqual(v['properties']['thread_occupancy'], 50)
        self.assertEqual(v['cycles']['total_cycles']['texture'], 3.875)
        self.assertFalse(v['properties']['has_stack_spilling'])

    def test_reject_wrong_target_schema_and_shape(self):
        with self.assertRaises(ValueError):
            summarize(self.raw, 'Mali-G720')
        bad = copy.deepcopy(self.raw)
        bad['schema']['version'] = 99
        with self.assertRaises(ValueError):
            summarize(bad, 'Immortalis-G720')
        self.raw['shaders'][0]['variants'][0]['performance']['total_cycles']['cycle_count'].pop()
        with self.assertRaises(ValueError):
            summarize(self.raw, 'Immortalis-G720')

    def test_comparison(self):
        report = dict(schema=1, config={}, slang={}, malioc={},
                      passes={'fit': {'mali': summarize(self.raw, 'Immortalis-G720')}})
        result = compare(report, report)
        self.assertEqual(result['fit']['Main']['properties']['work_registers_used'], 0)
        modified = copy.deepcopy(report)
        modified['passes']['fit']['mali']['driver'] = 'different'
        with self.assertRaises(ValueError):
            compare(report, modified)


if __name__ == '__main__':
    unittest.main()
