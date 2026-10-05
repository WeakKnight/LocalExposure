"""Production chains must recompute changed contents of the same HDR texture."""
import unittest
import numpy as np
import slangpy as spy
from tone_mapper import ROOT, ToneMapper, create_hdr_texture
from ue_local_exposure import UEParameters, UnrealLocalExposure


class ProductionGraphTests(unittest.TestCase):
    def test_half_bit_compatibility_preserves_every_finite_half(self):
        device = spy.Device(enable_hot_reload=False)
        bits = np.arange(65536, dtype=np.uint16).reshape(256, 256)
        # NaN payloads are outside the coefficient compatibility contract.
        bits[(bits & 0x7c00) == 0x7c00] = 0
        values = bits.view(np.float16).astype(np.float32)
        source = device.create_texture(width=256, height=256, format=spy.Format.r32_float,
            usage=spy.TextureUsage.shader_resource, data=values)
        out = device.create_texture(width=256, height=256, format=spy.Format.r32_uint,
            usage=spy.TextureUsage.shader_resource | spy.TextureUsage.unordered_access)
        defines = {'asuint16': 'f32tof16'} if device.info.type == spy.DeviceType.metal else {}
        session = device.create_slang_session(compiler_options={'defines': defines})
        kernel = device.create_compute_kernel(session.load_program(str(ROOT / 'tests/fixtures/half_pack_probe.slang'), ['pack_probe']))
        kernel.dispatch(thread_count=[256, 256, 1], vars=dict(inputTexture=source, outputTexture=out))
        np.testing.assert_array_equal(out.to_numpy(), bits.astype(np.uint32))

    def test_same_texture_content_change_and_diagnostic_parity(self):
        device = spy.Device(enable_hot_reload=False)
        source = create_hdr_texture(device, np.full((33, 65, 4), .12, np.float32))
        factories = [lambda s=s: ToneMapper(device, fusion_scale=s) for s in (1, 4)]
        factories += [lambda method=m: UnrealLocalExposure(device, method, parameters=UEParameters(profile='mobile'))
                      for m in ('ue-fusion', 'ue-bilateral')]
        for factory in factories:
            mapper, reference = factory(), factory()
            output = reference.create_output(source.width, source.height)
            encoder = device.create_command_encoder()
            mapper.record_processing(encoder, source, 0)
            device.submit_command_buffer(encoder.finish())
            first = mapper.final_color.to_numpy()
            encoder = device.create_command_encoder()
            encoder.clear_texture_float(source, clear_value=[.8, .4, .2, 1])
            mapper.record_processing(encoder, source, 0)
            reference.execute(encoder, source, output, 0)
            device.submit_command_buffer(encoder.finish())
            second = mapper.final_color.to_numpy()
            self.assertFalse(np.array_equal(first, second))
            np.testing.assert_array_equal(second, reference.final_color.to_numpy())
            encoder = device.create_command_encoder()
            encoder.clear_texture_float(source, clear_value=[.12, .12, .12, .12])
            device.submit_command_buffer(encoder.finish())
            device.wait()


if __name__ == '__main__':
    unittest.main()
