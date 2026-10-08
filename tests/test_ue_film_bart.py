"""Analytic curve compatibility against independent UE equations and graph."""
from dataclasses import replace
import unittest
from unittest.mock import patch, Mock

import numpy as np
import slangpy as spy

from fine_residual import FineResidualToneMapper
from main import Viewer, create_mapper, parse_args
from tone_mapper import ToneMapper, create_hdr_texture
from ue_local_exposure import UEParameters, UnrealLocalExposure
from tests import ue_reference as reference


class UEFilmBartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.device = spy.Device(enable_hot_reload=False)

    def render(self, mapper, rgba, ev=0, hi=1.2, sh=1.2, sigma=.2, production=False):
        source = create_hdr_texture(self.device, rgba)
        enc = self.device.create_command_encoder()
        mapper.prepare_weights(enc, source, ev, hi, sh, sigma)
        mapper.prepare_result(enc, source, ev, production=production)
        self.device.submit_command_buffer(enc.finish())
        return mapper.final_color.to_numpy()

    def test_scalar_equations_and_fixed_inverse_with_custom_film(self):
        defaults = UEParameters(luminance_method='uniform')
        for p in [defaults, replace(defaults, film_toe=.9),
                  replace(defaults, film_slope=1.1, film_white_clip=.08)]:
            m = ToneMapper(self.device, curve_mode='ue-film', film_parameters=p)
            for ev, hi, sh, sigma in [(0,0,0,.2), (-2,6,0,.02), (2,0,6,.8)]:
                # A one-row image has one pyramid level: pure scalar fusion.
                rgb = np.repeat(np.array([0,1e-6,.01,.18,1,4,8,16,100,65535],np.float32)[None,:,None],3,axis=-1)
                rgba = np.concatenate([rgb,np.ones((*rgb.shape[:2],1),np.float32)],axis=-1)
                lum = reference.eye_luminance(rgb*2**ev,p)
                y = np.sqrt(reference.film_neutral(lum[...,None]*np.exp2([-hi,0,sh]),p))
                logs = -(y-.5)**2/(2*sigma*sigma)
                weights = np.exp2(logs-logs.max(axis=-1,keepdims=True))
                weights /= weights.sum(axis=-1,keepdims=True)
                expected = reference.inverse_fusion(lum,(y*weights).sum(axis=-1))
                self.render(m,rgba,ev,hi,sh,sigma)
                np.testing.assert_allclose(m.local_exposure.to_numpy(),expected,rtol=.001,atol=2e-5)

    def test_full_graph_against_independent_ue_fp32(self):
        p = UEParameters(storage='fp32',luminance_method='uniform')
        m = ToneMapper(self.device,curve_mode='ue-film',film_parameters=p)
        u = UnrealLocalExposure(self.device,parameters=p)
        rng = np.random.default_rng(840)
        # Power-of-two sizes match both independent mip dimension conventions.
        for h,w in [(32,64),(128,128)]:
            rgba = np.exp2(rng.uniform(-10,8,(h,w,4))).astype(np.float32)
            for ev,hi,sh in [(0,1.2,1.2),(-2,6,0),(2,0,0)]:
                self.render(m,rgba,ev,hi,sh)
                source=create_hdr_texture(self.device,rgba)
                enc=self.device.create_command_encoder()
                u.execute(enc,source,u.create_output(w,h),ev,highlight_ev=hi,shadow_ev=sh)
                self.device.submit_command_buffer(enc.finish())
                np.testing.assert_allclose(m.local_exposure.to_numpy(),u.local_exposure.to_numpy(),rtol=.001,atol=2e-5)

    def test_optimized_edges_odd_sizes_and_production(self):
        m=FineResidualToneMapper(self.device,curve_mode='ue-film')
        for h,w in [(1,1),(3,7),(35,33),(289,513)]:
            rgba=np.full((h,w,4),.002,np.float32)
            rgba[:,w//2:]=[32,4,.1,1]
            for ev,hi,sh,sigma in [(0,1.2,1.2,.2),(-2,6,0,.02),(2,0,6,.8)]:
                debug=self.render(m,rgba,ev,hi,sh,sigma)
                gain=m.local_exposure.to_numpy()
                self.assertTrue(np.isfinite(debug).all())
                self.assertTrue(np.isfinite(gain).all())
                self.assertGreaterEqual(float(gain.min()),0)
                production=self.render(m,rgba,ev,hi,sh,sigma,production=True)
                np.testing.assert_array_equal(debug,production)

    def test_no_lookup_allocation_and_viewer_switching(self):
        v=Viewer.__new__(Viewer)
        v.device=self.device
        v.args=parse_args(['--fusion-curve','ue-film'])
        v.status,v.curve_selector,v.resolution_selector=Mock(),Mock(),Mock()
        with patch('fine_residual.ZCurve',side_effect=AssertionError('Z LUT allocated')), \
             patch('fine_residual.FusionLookup',side_effect=AssertionError('forward LUT allocated')), \
             patch('tone_mapper.ZCurve',side_effect=AssertionError('reference LUT allocated')):
            v.mapper=create_mapper(self.device,v.args)
            self.assertIsNone(v.mapper.lookup)
            v.set_resolution(1)
            self.assertIs(type(v.mapper),ToneMapper)
            self.assertEqual(v.mapper.curve_mode,'ue-film')
            v.set_resolution(0)
            v.mapper.reload()
            self.assertIsNone(v.mapper.lookup)
        v.set_curve(0)
        self.assertEqual(v.mapper.curve_mode,'z')
        v.set_curve(1)
        self.assertEqual(v.mapper.curve_mode,'ue-film')


if __name__ == '__main__':
    unittest.main()
