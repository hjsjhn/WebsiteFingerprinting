import unittest
import sys
import os
import json

# Add utils to path
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '../utils'))
from fec_injector import FECInjector

class TestFECInjector(unittest.TestCase):
    def test_strategy_A(self):
        injector = FECInjector('A')
        injector.process_real_packet(1)
        meta = injector.generate_dummy_content()
        self.assertEqual(meta['type'], 'DUMMY')
        self.assertEqual(meta['strategy'], 'A')

    def test_strategy_B(self):
        injector = FECInjector('B', block_size=2)
        
        # Block 0, Packet 1
        injector.process_real_packet(1)
        meta = injector.generate_dummy_content()
        self.assertEqual(meta['block_id'], 0)
        self.assertEqual(meta['protected_count'], 1)
        
        # Block 0, Packet 2
        injector.process_real_packet(2)
        # Now block 0 is full (size 2). current_block_id becomes 1. packets_in_current_block becomes 0.
        
        meta = injector.generate_dummy_content()
        # Should repair previous block (0)
        self.assertEqual(meta['block_id'], 0)
        self.assertEqual(meta['protected_count'], 2)
        self.assertEqual(meta['info'], "Previous Block Repair")
        
        # Block 1, Packet 3
        injector.process_real_packet(3)
        meta = injector.generate_dummy_content()
        self.assertEqual(meta['block_id'], 1)
        self.assertEqual(meta['protected_count'], 1)

    def test_strategy_C(self):
        injector = FECInjector('C', window_size=5)
        for i in range(1, 4):
            injector.process_real_packet(i)
            
        meta = injector.generate_dummy_content()
        self.assertEqual(meta['strategy'], 'C')
        self.assertTrue('degree' in meta)
        self.assertTrue('covered_ids' in meta)
        self.assertTrue(len(meta['covered_ids']) > 0)
        
    def test_strategy_D(self):
        injector = FECInjector('D', window_size=5)
        for i in range(1, 4):
            injector.process_real_packet(i)
            
        meta = injector.generate_dummy_content()
        self.assertEqual(meta['strategy'], 'D')
        self.assertEqual(meta['start_id'], 1)
        self.assertEqual(meta['end_id'], 3)
        
        # Advance window
        for i in range(4, 10):
            injector.process_real_packet(i)
            
        meta = injector.generate_dummy_content()
        # Window size is 5, head is 9. Window should be [5, 9]
        self.assertEqual(meta['start_id'], 5)
        self.assertEqual(meta['end_id'], 9)

if __name__ == '__main__':
    unittest.main()
