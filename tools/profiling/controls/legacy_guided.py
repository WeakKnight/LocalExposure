"""Frozen pre-fix Guided host, exclusively for historical benchmark controls.

Application code must use FineResidualToneMapper or the full-resolution ToneMapper.
"""
import numpy as np
import slangpy as spy
from tone_mapper import ROOT, fusion_mip_count
from zcurve import ZCurve

class LegacyGuidedToneMapper:
    def __init__(self, device: spy.Device, max_levels: int = 16, fusion_scale: int = 4):
        self.device = device
        if max_levels < 1:
            raise ValueError("max_levels must be positive")
        if fusion_scale not in (1, 4):
            raise ValueError("fusion_scale must be 1 or 4")
        self.fusion_scale = fusion_scale
        self.max_levels = max_levels
        self.sampler = device.create_sampler(min_filter=spy.TextureFilteringMode.linear,
                                             mag_filter=spy.TextureFilteringMode.linear,
                                             address_u=spy.TextureAddressingMode.clamp_to_edge,
                                             address_v=spy.TextureAddressingMode.clamp_to_edge)
        self.reload()

    def reload(self):
        # A fresh session also makes manual reload reliable after a compile error.
        session = self.device.create_slang_session(compiler_options={
            "include_paths": [ROOT / "shaders"]})
        program = session.load_program("tonemap.slang", ["compute_main"])
        kernel = self.device.create_compute_kernel(program)
        downsample = self.device.create_compute_kernel(session.load_program(str(ROOT / "tools/profiling/controls/pyramid_rec709.slang"), ["downsample"]))
        weights = self.device.create_compute_kernel(session.load_program(str(ROOT / "tools/profiling/controls/pyramid_rec709.slang"), ["setup_weights"]))
        reconstruct = self.device.create_compute_kernel(session.load_program(str(ROOT / "tools/profiling/controls/fusion_rec709.slang"), ["reconstruct"]))
        convert = self.device.create_compute_kernel(session.load_program(str(ROOT / "tools/profiling/controls/fusion_rec709.slang"), ["convert_exposure"]))
        guided_kernels = {name: self.device.create_compute_kernel(session.load_program(str(ROOT / "tools/profiling/controls/guided.slang"), [name]))
                          for name in ("reduce_source", "fit_coefficients", "average_coefficients", "apply_exposure")}
        curve = ZCurve(self.device, session=session)
        production_kernel = self.device.create_compute_kernel(session.load_program(str(ROOT / 'tools/profiling/controls/guided.slang'), ['apply_exposure_production']))
        self.curve = curve
        self.guided_kernels = guided_kernels
        self.production_kernel = production_kernel
        self.session, self.kernel = session, kernel
        self.downsample_kernel, self.weight_kernel = downsample, weights
        self.reconstruction_kernel, self.convert_kernel = reconstruct, convert
        self.reconstructed = self.local_exposure = self.final_color = None
        self._result_key = self._weight_key = None
        self.base_color = self.luminance_pyramid = self.weight_pyramid = None
        self._resource_key = self._reduced_source_key = None
        self.work_source = self.low_exposure = self.coefficients = self.averaged_coefficients = None

    def create_texture(self, width, height, format=spy.Format.rgba32_float, levels=1):
        return self.device.create_texture(
            width=width, height=height, format=format, mip_count=levels,
            usage=spy.TextureUsage.shader_resource | spy.TextureUsage.unordered_access)

    def build_pyramid(self, encoder, texture):
        for mip in range(1, texture.mip_count):
            self.downsample_kernel.dispatch(
                thread_count=[max(1, texture.width >> mip), max(1, texture.height >> mip), 1],
                vars={"inputTexture": texture.create_view(mip=mip - 1, mip_count=1),
                      "outputTexture": texture.create_view(mip=mip, mip_count=1),
                      "linearSampler": self.sampler}, command_encoder=encoder,
            )

    def prepare_weights(self, encoder, source, exposure_ev, highlight_ev, shadow_ev, sigma=0.2):
        if not np.isfinite(sigma) or sigma <= 0:
            raise ValueError("Weight sigma must be finite and positive")
        key = (source, exposure_ev, highlight_ev, shadow_ev, sigma, self.fusion_scale)
        if key == self._weight_key:
            return
        if self.fusion_scale not in (1, 4):
            raise ValueError("fusion_scale must be 1 or 4")
        resource_key = (source.width, source.height, self.fusion_scale)
        if resource_key != self._resource_key:
            width = (source.width + self.fusion_scale - 1) // self.fusion_scale
            height = (source.height + self.fusion_scale - 1) // self.fusion_scale
            levels = fusion_mip_count(width, height, self.max_levels)
            # SDR colors and bounded exposure multipliers use FP16 storage.
            # HDR, inverse-problem pyramids and guided coefficients stay FP32.
            self.base_color = self.create_texture(source.width, source.height, spy.Format.rgba16_float)
            self.final_color = self.create_texture(source.width, source.height, spy.Format.rgba16_float)
            self.local_exposure = self.create_texture(source.width, source.height, spy.Format.r16_float)
            self.luminance_pyramid = self.create_texture(width, height, levels=levels)
            self.weight_pyramid = self.create_texture(width, height, levels=levels)
            self.reconstructed = self.create_texture(width, height, spy.Format.r32_float, levels=levels)
            self.low_exposure = self.create_texture(width, height, spy.Format.r16_float)
            self.coefficients = self.create_texture(width, height, spy.Format.rg32_float)
            self.averaged_coefficients = self.create_texture(width, height, spy.Format.rg32_float)
            self.work_source = self.create_texture(width, height) if self.fusion_scale == 4 else source
            self._resource_key = resource_key
            self._reduced_source_key = self._result_key = None
        if self.fusion_scale == 1:
            self.work_source = source
        elif self._reduced_source_key != source:
            self.guided_kernels["reduce_source"].dispatch(
                thread_count=[self.work_source.width, self.work_source.height, 1],
                vars={"fullSource": source, "reducedOutput": self.work_source,
                      "linearSampler": self.sampler, "reductionRows": 4},
                command_encoder=encoder)
            self._reduced_source_key = source
        work = self.work_source
        self.weight_kernel.dispatch(
            thread_count=[work.width, work.height, 1],
            vars={**self.curve.bindings(), "hdrSource": work, "globalEV": exposure_ev,
                  "highlightEV": highlight_ev, "shadowEV": shadow_ev,
                  "luminanceOutput": self.luminance_pyramid.create_view(mip=0, mip_count=1),
                  "weightOutput": self.weight_pyramid.create_view(mip=0, mip_count=1), "sigma": sigma},
            command_encoder=encoder,
        )
        self.build_pyramid(encoder, self.luminance_pyramid)
        self.build_pyramid(encoder, self.weight_pyramid)
        self._weight_key = key

    def prepare_result(self, encoder, hdr_source, exposure_ev, production=False):
        result_key = (self._weight_key, 'production') if production else self._weight_key
        if self._result_key == result_key:
            return
        work = self.work_source
        last = self.reconstructed.mip_count - 1
        for mip in range(last, -1, -1):
            # Bind an independent SRV for the base case (branch doesn't read it).
            previous = self.low_exposure if mip == last else self.reconstructed.create_view(mip=mip+1, mip_count=1)
            self.reconstruction_kernel.dispatch(
                thread_count=[max(1, work.width >> mip), max(1, work.height >> mip), 1],
                vars={"fineLuminance": self.luminance_pyramid.create_view(mip=mip, mip_count=1),
                      "coarseLuminance": self.luminance_pyramid.create_view(mip=min(mip+1, last), mip_count=1),
                      "layerWeights": self.weight_pyramid.create_view(mip=mip, mip_count=1),
                      "previousResult": previous, "linearSampler": self.sampler, "isCoarsest": mip == last,
                      "reconstructionOutput": self.reconstructed.create_view(mip=mip, mip_count=1)},
                command_encoder=encoder)
        self.convert_kernel.dispatch(thread_count=[work.width, work.height, 1],
            vars={**self.curve.bindings(), "hdrSource": work, "fusedLightness": self.reconstructed,
                  "globalEV": exposure_ev, "exposureOutput": self.low_exposure},
            command_encoder=encoder)
        if self.fusion_scale == 4:
            self.guided_kernels["fit_coefficients"].dispatch(
                thread_count=[work.width, work.height, 1],
                vars={"reducedSource": work, "lowExposure": self.low_exposure,
                      "coefficientOutput": self.coefficients}, command_encoder=encoder)
            self.guided_kernels["average_coefficients"].dispatch(
                thread_count=[work.width, work.height, 1],
                vars={"coefficients": self.coefficients, "averagedOutput": self.averaged_coefficients},
                command_encoder=encoder)
        (self.production_kernel if production else self.guided_kernels["apply_exposure"]).dispatch(
            thread_count=[hdr_source.width, hdr_source.height, 1],
            vars={"fullSource": hdr_source, "lowExposure": self.low_exposure,
                  "averagedCoefficients": self.averaged_coefficients, "linearSampler": self.sampler,
                  "globalEV": exposure_ev, "guided": self.fusion_scale == 4,
                  "colorOutput": self.final_color,
                  **({} if production else {"fullExposureOutput": self.local_exposure,
                                             "baseOutput": self.base_color})}, command_encoder=encoder)
        self._result_key = result_key

    def record_processing(self, encoder, source, exposure_ev, highlight_ev=1.2, shadow_ev=1.2, sigma=.2):
        # Benchmark/animated inputs: record every pass even when the texture and
        # parameters have not changed. Keep viewer caching and reference intact.
        self._weight_key = self._result_key = self._reduced_source_key = None
        self.prepare_weights(encoder, source, exposure_ev, highlight_ev, shadow_ev, sigma)
        self.prepare_result(encoder, source, exposure_ev, production=True)

    def create_output(self, width: int, height: int) -> spy.Texture:
        # Values are already sRGB encoded: use UNORM, not an sRGB texture.
        return self.create_texture(width, height, spy.Format.rgba8_unorm)

    def execute(self, encoder, source, output, exposure_ev, view_mode=0,
                highlight_ev=1.2, shadow_ev=1.2, sigma=0.2):
        self.prepare_weights(encoder, source, exposure_ev, highlight_ev, shadow_ev, sigma)
        self.prepare_result(encoder, source, exposure_ev)
        self.kernel.dispatch(
            thread_count=[output.width, output.height, 1],
            vars={"source": self.base_color, "output": output,
                  "localExposure": self.local_exposure, "finalColor": self.final_color,
                  "linearSampler": self.sampler, "viewMode": view_mode},
            command_encoder=encoder)

