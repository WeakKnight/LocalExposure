"""Lossless production compaction against the independent legacy pipeline."""
import unittest
import numpy as np
import slangpy as spy
from tone_mapper import ToneMapper, create_hdr_texture, ROOT

class CompactTests(unittest.TestCase):
    def test_fused_graph_matches_legacy(self):
        device=spy.Device(enable_hot_reload=False)
        session=device.create_slang_session(compiler_options={'include_paths':[ROOT/'shaders']})
        kernels={name:device.create_compute_kernel(session.load_program(str(ROOT/'tests/fixtures/fusion_compact_reference.slang'),[name]))
                 for name in ('reduce_setup','reconstruct_compact','reconstruct_guided','downsample_compact')}
        mapper=ToneMapper(device)
        rng=np.random.default_rng(6517)
        for h,w,ev,bracket in [(1,1,0,1.2),(1,9,-8,0),(17,31,4,2),(63,97,0,1.2),(128,256,0,6),(181,321,-1.25,1.2),(63,97,16,0),(17,31,-16,1.2)]:
            with self.subTest(size=(h,w),ev=ev,bracket=bracket):
                rgba=np.minimum(np.exp2(rng.uniform(-35,16,(h,w,4))),65535).astype(np.float32)
                rgba.reshape(-1,4)[::13,:3]=0
                rgba.reshape(-1,4)[::31,:3]=[-1,65535,1e-8]
                source=create_hdr_texture(device,rgba)
                enc=device.create_command_encoder()
                mapper.prepare_weights(enc,source,ev,bracket,bracket)
                mapper.prepare_result(enc,source,ev)
                lw,lh=mapper.work_source.width,mapper.work_source.height
                levels=mapper.reconstructed.mip_count
                compact=mapper.create_texture(lw,lh,spy.Format.rg32_float)
                lum=mapper.create_texture(lw,lh,levels=levels)
                weights=mapper.create_texture(lw,lh,spy.Format.rg32_float,levels=levels)
                recon=mapper.create_texture(lw,lh,spy.Format.r32_float,levels=levels)
                averaged=mapper.create_texture(lw,lh,spy.Format.rg32_float)
                view=lambda texture,mip=0:texture.create_view(mip=mip,mip_count=1)
                def dispatch(name,width,height,**bindings):
                    kernels[name].dispatch(thread_count=[width,height,1],vars=bindings,command_encoder=enc)
                dispatch('reduce_setup',lw,lh,fullSource=source,compactOutput=compact,
                    lightnessOutput=view(lum),weightsOutput=view(weights),linearSampler=mapper.sampler,
                    reductionRows=4,globalEV=ev,highlightEV=bracket,shadowEV=bracket,sigma=.2,**mapper.curve.bindings())
                for mip in range(1,levels):
                    dispatch('downsample_compact',max(1,lw>>mip),max(1,lh>>mip),
                             coarseLuminance=view(lum,mip-1),layerWeights=view(weights,mip-1),
                             lightnessOutput=view(lum,mip),weightsOutput=view(weights,mip),linearSampler=mapper.sampler)
                for mip in reversed(range(levels)):
                    vars=dict(fineLuminance=view(lum,mip),coarseLuminance=view(lum,min(mip+1,levels-1)),
                              layerWeights=view(weights,mip),previousResult=compact if mip==levels-1 else view(recon,mip+1),
                              linearSampler=mapper.sampler,isCoarsest=mip==levels-1)
                    if mip:
                        dispatch('reconstruct_compact',max(1,lw>>mip),max(1,lh>>mip),reconstructionOutput=view(recon,mip),**vars)
                    else:
                        dispatch('reconstruct_guided',lw,lh,compactSource=compact,averagedOutput=averaged,
                                 globalEV=ev,**mapper.curve.bindings(),**vars)
                device.submit_command_buffer(enc.finish())
                for mip in range(levels):
                    a=lum.to_numpy(mip=mip); b=mapper.luminance_pyramid.to_numpy(mip=mip)
                    c=weights.to_numpy(mip=mip); d=mapper.weight_pyramid.to_numpy(mip=mip)
                    np.testing.assert_array_equal(a[...,:3],b[...,:3])
                    np.testing.assert_array_equal(a[...,3],d[...,0])
                    np.testing.assert_array_equal(c,d[...,1:3])
                a=averaged.to_numpy(); b=mapper.averaged_coefficients.to_numpy()
                self.assertTrue(np.isfinite(a).all())
                np.testing.assert_array_equal(a.view(np.uint32),b.view(np.uint32))
