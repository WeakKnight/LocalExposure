"""The residual formulation must preserve normalized multiscale exposure fusion."""
import unittest
import numpy as np

class ResidualFusionTests(unittest.TestCase):
    def test_common_exposure_cancels_for_arbitrary_linear_pyramids(self):
        rng=np.random.default_rng(293)
        sizes=[19,9,4,1]
        def matrix(rows,columns):
            a=rng.random((rows,columns));return a/a.sum(axis=1,keepdims=True)
        down=[matrix(b,a) for a,b in zip(sizes,sizes[1:])]
        up=[matrix(a,b) for a,b in zip(sizes,sizes[1:])]
        for scale in [1e-6,1.,100.]:
            levels=[rng.random((sizes[0],3))*scale]
            weights=[]
            for d in down:levels.append(d@levels[-1])
            for size in sizes:
                w=rng.random((size,3));weights.append(w/w.sum(axis=1,keepdims=True))
            original=np.sum(levels[-1]*weights[-1],axis=1)
            deltas=[y[:,[0,2]]-y[:,1,None] for y in levels]
            residual=np.sum(deltas[-1]*weights[-1][:,[0,2]],axis=1)
            for level in range(len(sizes)-2,-1,-1):
                original=np.sum((levels[level]-up[level]@levels[level+1])*weights[level],axis=1)+up[level]@original
                residual=np.sum((deltas[level]-up[level]@deltas[level+1])*weights[level][:,[0,2]],axis=1)+up[level]@residual
            np.testing.assert_allclose(levels[0][:,1]+residual,original,rtol=1e-13,atol=scale*1e-14)

    def test_identical_brackets_have_zero_residual_at_every_level(self):
        y=np.geomspace(1e-8,1,97)
        exposures=np.repeat(y[:,None],3,axis=1)
        residual=exposures[:,[0,2]]-exposures[:,1,None]
        np.testing.assert_array_equal(residual,np.zeros_like(residual))
