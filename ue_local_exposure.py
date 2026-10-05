"""Independent UE 5.8 Local Exposure graphs; the Bart reference is unchanged.

Source correspondence and intentional host/precision differences are documented
in docs/unreal-local-exposure.md. Viewer readbacks are outside production timing.
"""
from dataclasses import asdict, dataclass
import math

import numpy as np
import slangpy as spy

from tone_mapper import ROOT, fusion_mip_count


@dataclass(frozen=True)
class UEParameters:
    profile: str = 'desktop'
    storage: str = 'native'
    histogram_min: float = -8.0
    histogram_max: float = 4.0
    luminance_method: str = 'uniform'
    pre_exposure: float = 1.0
    grey_multiplier: float = 1.0
    middle_grey_bias: float = 0.0
    detail_strength: float = 1.0
    blurred_blend: float = 0.6
    blur_percent: float = 50.0
    highlight_threshold: float = 0.0
    shadow_threshold: float = 0.0
    highlight_threshold_strength: float = 1.0
    shadow_threshold_strength: float = 1.0
    target_luminance: float = 0.5
    film_slope: float = 0.88
    film_toe: float = 0.55
    film_shoulder: float = 0.26
    film_black_clip: float = 0.0
    film_white_clip: float = 0.04

    def __post_init__(self):
        for name, value in asdict(self).items():
            if isinstance(value, (float, int)) and not math.isfinite(value):
                raise ValueError(f'{name} must be finite')
        if self.profile not in ('desktop', 'mobile') or self.storage not in ('native', 'fp32'):
            raise ValueError('Invalid UE profile or storage')
        if self.luminance_method not in ('uniform', 'rec709', 'ntsc'):
            raise ValueError('Invalid UE luminance method')
        if self.histogram_max - self.histogram_min < 1 or not -40 <= self.histogram_min < self.histogram_max <= 40:
            raise ValueError('Histogram must span at least one stop within [-40, 40]')
        if self.pre_exposure <= 0 or self.grey_multiplier <= 0 or self.film_slope <= 0:
            raise ValueError('Exposure, grey multiplier and film slope must be positive')
        for name in ('blurred_blend', 'highlight_threshold_strength', 'shadow_threshold_strength', 'target_luminance'):
            if not 0 <= getattr(self, name) <= 1:
                raise ValueError(f'{name} must be in [0, 1]')
        if self.detail_strength < 0 or not 0 <= self.blur_percent <= 100:
            raise ValueError('Detail strength must be nonnegative and blur percent in [0, 100]')
        if self.highlight_threshold < 0 or self.shadow_threshold < 0:
            raise ValueError('Thresholds must be nonnegative')
        if not 0 < 1 + self.film_black_clip - self.film_toe or not 0 < 1 + self.film_white_clip - self.film_shoulder:
            raise ValueError('Film toe and shoulder scales must be positive')
        if abs(self.film_toe + self.film_shoulder - 1) < 1e-6:
            raise ValueError('Film toe and shoulder must have distinct match points')
        if self.film_toe <= .8 and not 0 < (.18 + self.film_black_clip) / (1 + self.film_black_clip - self.film_toe) < 2:
            raise ValueError('Film toe must have a valid middle-grey match')

    @property
    def luminance_weights(self):
        return {'uniform': (1 / 3, 1 / 3, 1 / 3), 'rec709': (.2126, .7152, .0722),
                'ntsc': (.3, .59, .11)}[self.luminance_method]

    def bindings(self, ev, highlight=.8, shadow=.8):
        return dict(luminanceWeights=self.luminance_weights, histogramMin=self.histogram_min,
            histogramMax=self.histogram_max, globalEV=ev, preExposure=self.pre_exposure,
            highlightContrast=highlight, shadowContrast=shadow, detailStrength=self.detail_strength,
            blurredBlend=self.blurred_blend, middleGreyBias=self.middle_grey_bias,
            greyMultiplier=self.grey_multiplier, highlightThreshold=self.highlight_threshold,
            shadowThreshold=self.shadow_threshold, highlightThresholdStrength=self.highlight_threshold_strength,
            shadowThresholdStrength=self.shadow_threshold_strength, filmSlope=self.film_slope,
            filmToe=self.film_toe, filmShoulder=self.film_shoulder, filmBlackClip=self.film_black_clip,
            filmWhiteClip=self.film_white_clip, targetLuminance=self.target_luminance)


def gaussian_taps(radius):
    """UE's default desktop r.Filter.SizeScale=1, r.Filter.LoopMode=0."""
    radius = np.float32(np.clip(radius, 1e-5, 31))
    integer_radius = max(1, math.ceil(float(radius)))
    taps = []
    for i in range(-integer_radius, integer_radius + 1, 2):
        w0 = np.float32(np.exp(np.float32(-16.7) * (np.float32(i) / radius) ** 2))
        w1 = np.float32(0) if i == integer_radius else np.float32(np.exp(np.float32(-16.7) * (np.float32(i + 1) / radius) ** 2))
        total = w0 + w1
        # At radius 0 UE can produce 0/0 for off-center taps. Keep the
        # zero-radius limit finite without changing nonzero tap contributions.
        taps.append((np.float32(i) + (w1 / total if total > 0 else 0), total))
    result = np.asarray(taps, np.float32)
    result[:, 1] /= result[:, 1].sum(dtype=np.float32)
    return result


class UnrealLocalExposure:
    def __init__(self, device, method='ue-fusion', max_levels=16, parameters=None):
        if method not in ('ue-fusion', 'ue-bilateral') or max_levels < 1:
            raise ValueError('Invalid UE method or level count')
        self.device, self.method, self.max_levels = device, method, max_levels
        self.parameters = parameters or UEParameters()
        self.sampler = device.create_sampler(min_filter=spy.TextureFilteringMode.linear,
            mag_filter=spy.TextureFilteringMode.linear, address_u=spy.TextureAddressingMode.clamp_to_edge,
            address_v=spy.TextureAddressingMode.clamp_to_edge, address_w=spy.TextureAddressingMode.clamp_to_edge)
        self.point_sampler = device.create_sampler(address_u=spy.TextureAddressingMode.clamp_to_edge,
            address_v=spy.TextureAddressingMode.clamp_to_edge)
        self.mirror_sampler = device.create_sampler(min_filter=spy.TextureFilteringMode.linear,
            mag_filter=spy.TextureFilteringMode.linear, address_u=spy.TextureAddressingMode.mirror_repeat,
            address_v=spy.TextureAddressingMode.mirror_repeat)
        self.reload()

    def reload(self):
        session = self.device.create_slang_session(compiler_options={'include_paths': [ROOT / 'shaders']})
        stages = dict(downsample=('unreal/downsample.slang', 'downsample_ue'),
            display=('tonemap.slang', 'compute_main'), baseline=('unreal/apply.slang', 'apply_baseline'))
        if self.method == 'ue-fusion':
            stages.update(setup=('unreal/fusion.slang', 'setup_fusion'), blend=('unreal/fusion.slang', 'blend_fusion'),
                          apply=('unreal/apply.slang', 'apply_fusion'), inspect=('unreal/apply.slang', 'inspect_fusion'))
        else:
            stages.update(grid=('unreal/bilateral.slang', 'build_grid'), log=('unreal/bilateral.slang', 'setup_log'),
                          blur=('unreal/bilateral.slang', 'blur_log'), apply=('unreal/apply.slang', 'apply_bilateral'),
                          inspect=('unreal/apply.slang', 'inspect_bilateral'))
        kernels = {name: self.device.create_compute_kernel(session.load_program(file, [entry]))
                   for name, (file, entry) in stages.items()}
        self.session, self.kernels = session, kernels
        self._resource_key = self._result_key = None

    def create_texture(self, width, height, format=spy.Format.rgba32_float):
        return self.device.create_texture(width=width, height=height, format=format,
            usage=spy.TextureUsage.shader_resource | spy.TextureUsage.unordered_access)

    def create_output(self, width, height):
        return self.create_texture(width, height, spy.Format.rgba8_unorm)

    def allocate(self, source):
        w, h = source.width, source.height
        key = (w, h, self.parameters, self.max_levels)
        if key == self._resource_key:
            return
        p = self.parameters
        rgb_format = spy.Format.r11g11b10_float if p.storage == 'native' else spy.Format.rgba32_float
        scalar_format = spy.Format.r16_float if p.storage == 'native' else spy.Format.r32_float
        self.final_color = self.create_texture(w, h, spy.Format.rgba16_float)
        self.base_color = self.create_texture(w, h, spy.Format.rgba16_float)
        self.local_exposure = self.create_texture(w, h, spy.Format.r32_float)
        if self.method == 'ue-fusion':
            sizes = [(w, h)]
            for _ in range(1, fusion_mip_count(w, h, self.max_levels)):
                sizes.append(tuple((x + 1) // 2 for x in sizes[-1]))
            self.exposures = [self.create_texture(*s, rgb_format) for s in sizes]
            self.weights = [self.create_texture(*s, rgb_format) for s in sizes]
            # UE inherits PF_FloatRGB for the reconstruction as well.
            self.results = [self.create_texture(*s, rgb_format) for s in sizes]
        else:
            self.scene_chain = [source]
            if p.profile == 'desktop':
                for _ in range(5):
                    previous = self.scene_chain[-1]
                    self.scene_chain.append(self.create_texture((previous.width + 1) // 2,
                        (previous.height + 1) // 2, rgb_format))
            self.grid_source = self.scene_chain[1] if p.profile == 'desktop' else source
            self.log_source = self.scene_chain[-1]
            gw, gh = (self.grid_source.width + 63) // 64, (self.grid_source.height + 63) // 64
            self.grid = self.device.create_texture(type=spy.TextureType.texture_3d,
                width=gw, height=gh, depth=32, format=spy.Format.rg32_float,
                usage=spy.TextureUsage.shader_resource | spy.TextureUsage.unordered_access)
            self.grid_uv_scale = (self.grid_source.width / (64 * gw), self.grid_source.height / (64 * gh))
            lw, lh = self.log_source.width, self.log_source.height
            radius = lw * p.blur_percent * .005
            self.log_texture = self.create_texture(lw, lh, scalar_format)
            self.blur_x = self.create_texture((lw + 1) // 2 if radius >= 7 else lw, lh, scalar_format)
            self.blurred_log = self.create_texture(lw, lh, scalar_format)
            self.taps = gaussian_taps(radius)
            self.tap_buffer = self.device.create_buffer(struct_size=8, element_count=len(self.taps),
                usage=spy.BufferUsage.shader_resource, data=self.taps)
        self._resource_key, self._result_key = key, None

    def dispatch(self, name, encoder, output, bindings):
        self.kernels[name].dispatch(thread_count=[output.width, output.height, 1],
            vars=bindings, command_encoder=encoder)

    def downsample(self, encoder, source, output, high=True):
        self.dispatch('downsample', encoder, output, dict(inputTexture=source, outputTexture=output,
            linearSampler=self.sampler, highQuality=high))

    def record_preparation(self, encoder, source, ev, highlight=.8, shadow=.8):
        """Always record the entire graph, including shared scene reduction.

        Called without viewer caching by the benchmark. No uploads, calibration,
        diagnostic exposure writes or visualization dispatches are recorded here.
        """
        self.allocate(source)
        params = self.parameters.bindings(ev, highlight, shadow)
        if self.method == 'ue-fusion':
            self.dispatch('setup', encoder, self.exposures[0], dict(params,
                hdrSource=source, exposuresOutput=self.exposures[0], weightsOutput=self.weights[0]))
            for chain in (self.exposures, self.weights):
                for previous, current in zip(chain, chain[1:]):
                    self.downsample(encoder, previous, current)
            for index in range(len(self.results) - 1, -1, -1):
                coarse = min(index + 1, len(self.results) - 1)
                self.dispatch('blend', encoder, self.results[index], dict(fineLuminance=self.exposures[index],
                    coarseLuminance=self.exposures[coarse], layerWeights=self.weights[index],
                    previousResult=self.results[coarse] if coarse != index else self.exposures[index],
                    linearSampler=self.sampler, reconstructionOutput=self.results[index], isCoarsest=coarse == index))
        else:
            if self.parameters.profile == 'desktop':
                for i, (previous, current) in enumerate(zip([source, *self.scene_chain[1:-1]], self.scene_chain[1:])):
                    self.downsample(encoder, previous, current, high=i > 0)
            # Mobile source changes of the same dimensions must update bindings.
            grid_source = self.grid_source if self.parameters.profile == 'desktop' else source
            log_source = self.log_source if self.parameters.profile == 'desktop' else source
            self.kernels['grid'].dispatch(thread_count=[self.grid.width * 8, self.grid.height * 8, 1],
                vars=dict(params, hdrSource=grid_source, pointSampler=self.point_sampler, gridOutput=self.grid), command_encoder=encoder)
            # At zero blend UE skips log setup and Gaussian passes. Empty-grid
            # fallback reads the black dummy instead; keep that behavior.
            if self.parameters.blurred_blend > 0:
                self.dispatch('log', encoder, self.log_texture, dict(params, hdrSource=log_source, logOutput=self.log_texture))
                common = dict(blurTaps=self.tap_buffer, tapCount=len(self.taps), mirrorSampler=self.mirror_sampler)
                self.dispatch('blur', encoder, self.blur_x, dict(common, blurInput=self.log_texture,
                    blurOutput=self.blur_x, blurAxis=(1 / self.log_texture.width, 0)))
                self.dispatch('blur', encoder, self.blurred_log, dict(common, blurInput=self.blur_x,
                    blurOutput=self.blurred_log, blurAxis=(0, 1 / self.log_texture.height)))
            else:
                encoder.clear_texture_float(self.blurred_log, clear_value=[0, 0, 0, 0])

    def apply_bindings(self, source, ev, highlight=.8, shadow=.8, inspect=False):
        bindings = dict(self.parameters.bindings(ev, highlight, shadow), hdrSource=source,
                        colorOutput=self.final_color, linearSampler=self.sampler)
        if self.method == 'ue-fusion':
            bindings['fusedResult'] = self.results[0]
        else:
            bindings.update(bilateralGrid=self.grid, blurredLog=self.blurred_log, gridUVScale=self.grid_uv_scale)
        if inspect:
            bindings.update(baseOutput=self.base_color, exposureOutput=self.local_exposure)
        return bindings

    def record_processing(self, encoder, source, ev, highlight=.8, shadow=.8):
        self.record_preparation(encoder, source, ev, highlight, shadow)
        self.dispatch('apply', encoder, self.final_color, self.apply_bindings(source, ev, highlight, shadow))
        self._result_key = None

    def execute(self, encoder, source, output, exposure_ev, view_mode=0, highlight_ev=1.2, shadow_ev=1.2, sigma=.2):
        highlight, shadow = 1 - highlight_ev / 6, 1 - shadow_ev / 6
        self.allocate(source)
        key = (source, exposure_ev, highlight, shadow, self.parameters)
        if key != self._result_key:
            self.record_preparation(encoder, source, exposure_ev, highlight, shadow)
            self.dispatch('inspect', encoder, self.final_color,
                          self.apply_bindings(source, exposure_ev, highlight, shadow, inspect=True))
            self._result_key = key
        self.dispatch('display', encoder, output, dict(source=self.base_color, output=output,
            localExposure=self.local_exposure, finalColor=self.final_color, linearSampler=self.sampler, viewMode=view_mode))
