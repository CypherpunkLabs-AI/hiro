import json
from pathlib import Path
import runpy
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
select = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/capture-platform'))['select_evidence']


class CaptureTests(unittest.TestCase):
    def test_replica_selection_and_composition_are_bound_to_the_deployment(self):
        selected = {'instance_id': 'a' * 40, 'quote': '0x0011', 'vm_config': '{"cpu_count": 4}',
                    'tcb_info': {'app_compose': '{"exact": true}', 'event_log': [{'imr': 3}]}}
        other = dict(selected, instance_id='b' * 40, quote='0xffff')
        result = select({'instances': [{'instance_id': None}, other, selected]}, 'a' * 40, b'{"exact": true}')
        self.assertEqual(result['quote'], '0011')
        self.assertEqual(json.loads(result['event_log']), [{'imr': 3}])
        with self.assertRaisesRegex(ValueError, 'composition changed'):
            select({'instances': [selected]}, 'a' * 40, b'{"different": true}')
        with self.assertRaisesRegex(ValueError, 'deployed instance'):
            select({'instances': [other]}, 'a' * 40, b'{"exact": true}')


if __name__ == '__main__':
    unittest.main()
