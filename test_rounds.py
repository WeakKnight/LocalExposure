"""Compare the optimized pipeline with the frozen pre-ten-rounds implementation."""
from pathlib import Path
import unittest
import numpy as np
import slangpy as spy
from tone_mapper import ToneMapper, create_hdr_texture

ROOT = Path(__file__).resolve().parent


class RoundTests(unittest.TestCase):
    def test_pipeline_bitwise(self):
        device = spy.Device(enable_hot_reload=False)
        old, new = ToneMapper(device), ToneMapper(device)
        session = device.create_slang_session(compiler_options={
            'include_paths':[ROOT/'shaders', ROOT/'tests/fixtures']})
        for entry in old.guided_kernels:
            old.guided_kernels[entry] = device.create_compute_kernel(
                session.load_program('guided_before_ten_rounds.slang',[entry]))
        old.kernel = device.create_compute_kernel(
            session.load_program('tonemap_before_ten_rounds.slang',['compute_main']))
        rng = np.random.default_rng(202610)
        for h,w,ev,bracket in [(1,1,0,0),(9,1,-16,1.2),(17,31,16,0),(63,97,0,1.2),(128,256,0,6)]:
            rgba = np.minimum(np.exp2(rng.uniform(-35,16,(h,w,4))),65535).astype(np.float32)
            rgba.reshape(-1,4)[::13,:3] = 0
            rgba.reshape(-1,4)[::31,:3] = [-1,65535,1e-8]
            source = create_hdr_texture(device,rgba)
            for scale in [1,4]:
                old.fusion_scale = new.fusion_scale = scale
                for mode in [0,1,2]:
                    with self.subTest(size=(h,w),scale=scale,mode=mode):
                        outs = [m.create_output(w+3,h+5) for m in [old,new]]
                        encoder = device.create_command_encoder()
                        for mapper,out in zip([old,new],outs):
                            mapper.execute(encoder,source,out,ev,view_mode=mode,
                                           highlight_ev=bracket,shadow_ev=bracket)
                        device.submit_command_buffer(encoder.finish())
                        np.testing.assert_array_equal(outs[0].to_numpy(),outs[1].to_numpy())
                        names = ['work_source','low_exposure','local_exposure','base_color','final_color']
                        if scale == 4:
                            names += ['coefficients','averaged_coefficients']
                        for name in names:
                            a,b = [getattr(m,name).to_numpy() for m in [old,new]]
                            np.testing.assert_array_equal(a.view(np.uint8),b.view(np.uint8),err_msg=name)


if __name__ == '__main__':
    unittest.main()
