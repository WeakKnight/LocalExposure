import unittest
import numpy as np
from tools.profiling.android.quality import image_quality

class QualityTests(unittest.TestCase):
    def test_small_error_and_alpha_ignored(self):
        a=np.full((64,64,4),100,np.uint8); b=a.copy()
        b[0,0,0]+=1; b[...,3]=0
        self.assertTrue(image_quality(a,b)['accepted'])

    def test_visible_global_shift_or_single_large_outlier_rejected(self):
        a=np.full((64,64,4),100,np.float32)
        self.assertFalse(image_quality(a,a+2)['accepted'])
        b=a.copy(); b[0,0,0]+=13
        self.assertFalse(image_quality(a,b)['accepted'])
        b[0,0,0]=float('nan')
        self.assertFalse(image_quality(a,b)['accepted'])

    def test_shape_mismatch_rejected(self):
        with self.assertRaises(ValueError): image_quality(np.zeros((3,3,4)),np.zeros((2,2,4)))
