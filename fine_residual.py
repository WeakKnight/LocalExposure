"""Interactive host for the retained quarter-resolution fine-residual graph.

ToneMapper remains the independent full-resolution control.
This host uses the same stage shaders and storage as the mobile default, with
an additional diagnostic apply entry for the viewer's comparison and EV map.
"""
import math
import slangpy as spy

from fusion_lookup import FusionLookup
from tone_mapper import ROOT, ToneMapper, fusion_mip_count
from zcurve import ZCurve
from ue_film_curve import UEFilmCurve


class FineResidualToneMapper(ToneMapper):
    def __init__(self, device, max_levels=16, curve_mode='z', film_parameters=None):
        super().__init__(device, max_levels, curve_mode=curve_mode, film_parameters=film_parameters)
        self.fusion_scale = 4

    def reload(self):
        session = self.device.create_slang_session(compiler_options={
            'include_paths': [ROOT / 'shaders']})
        stages = {
            'initialize': ('fine_residual/initialize', 'reduce_setup_gather'),
            'downsample': ('compact/pyramid', 'downsample_compact'),
            'tail': ('compact/tail', 'tail_reconstruct'),
            'reconstruct': ('fine_residual/reconstruct', 'reconstruct_compact'),
            'finish': ('fine_residual/reconstruct', 'reconstruct_ev'),
            'finish_fused': ('fine_residual/reconstruct', 'reconstruct_ev_fused'),
            'apply': ('fine_residual/apply', 'apply_exposure'),
            'production': ('fine_residual/apply', 'apply_exposure_production'),
        }
        analytic = self.curve_mode == 'ue-film'
        if analytic:
            for name in ('initialize', 'apply', 'production'):
                module, entry = stages[name]
                stages[name] = (module + '_ue_film', entry)
        kernels = {name: self.device.create_compute_kernel(session.load_program(
            module + '.slang', [entry])) for name, (module, entry) in stages.items()}
        kernel = self.device.create_compute_kernel(session.load_program('tonemap.slang', ['compute_main']))
        curve = UEFilmCurve(self.film_parameters) if analytic else ZCurve(self.device, session=session)
        self.session, self.kernels, self.kernel, self.curve = session, kernels, kernel, curve
        self.lookup = None if analytic else FusionLookup(self.device)
        self._resource_key = self._weight_key = self._result_key = None
        self.final_color = self.base_color = self.local_exposure = None

    def allocate(self, source):
        key = (source.width, source.height)
        if key == self._resource_key:
            return
        w, h = (source.width + 3) // 4, (source.height + 3) // 4
        self.levels = fusion_mip_count(w, h, self.max_levels)
        self.compact = self.create_texture(w, h, spy.Format.rg16_float)
        self.base_lightness = self.create_texture(w, h, spy.Format.r32_float)
        self.fine_pyramid = self.create_texture(w, h, spy.Format.rgba16_float,
                                                levels=min(3, self.levels))
        self.coarse_pyramid = (self.create_texture(max(1, w >> 3), max(1, h >> 3),
            spy.Format.rgba32_float, levels=self.levels - 3) if self.levels > 3 else None)
        self.reconstructed = self.create_texture(w, h, spy.Format.r32_float, levels=self.levels)
        self.residual = self.create_texture(w, h, spy.Format.rg16_float)
        self.final_color = self.create_texture(*key, spy.Format.rgba16_float)
        self.base_color = self.create_texture(*key, spy.Format.rgba16_float)
        self.local_exposure = self.create_texture(*key, spy.Format.r16_float)
        self._resource_key, self._weight_key, self._result_key = key, None, None

    def pyramid_view(self, mip):
        texture = self.fine_pyramid if mip < 3 else self.coarse_pyramid
        return texture.create_view(mip=mip if mip < 3 else mip - 3, mip_count=1)

    def dispatch(self, encoder, name, width, height, **bindings):
        self.kernels[name].dispatch(thread_count=[width, height, 1], vars=bindings,
                                    command_encoder=encoder)

    def prepare_weights(self, encoder, source, exposure_ev, highlight_ev, shadow_ev, sigma=.2):
        if not all(math.isfinite(v) for v in (exposure_ev, highlight_ev, shadow_ev, sigma)) or sigma <= 0:
            raise ValueError('Finite exposure parameters and positive sigma required')
        self.allocate(source)
        curve_key = tuple(self.curve.bindings().values()) if self.curve_mode == 'ue-film' else None
        key = (source, exposure_ev, highlight_ev, shadow_ev, sigma, curve_key)
        if key == self._weight_key:
            return
        if self.curve_mode == 'ue-film':
            self.lookup_bindings = dict(self.curve.bindings(), highlightEV=highlight_ev,
                                        shadowEV=shadow_ev, sigma=sigma)
        else:
            self.lookup_bindings = self.lookup.prepare(self.curve, highlight_ev, shadow_ev, sigma)
        w, h = self.compact.width, self.compact.height
        self.dispatch(encoder, 'initialize', w, h, fullSource=source,
            linearSampler=self.sampler, globalEV=exposure_ev, **self.lookup_bindings,
            compactOutput=self.compact, baseLightnessOutput=self.base_lightness,
            lightnessOutput=self.pyramid_view(0))
        self.tail_mip = 1
        while self.tail_mip < self.levels - 1 and (
                max(1, w >> self.tail_mip) > 16 or max(1, h >> self.tail_mip) > 8):
            self.tail_mip += 1
        self.use_tail = self.tail_mip < self.levels - 1
        for mip in range(1, self.tail_mip + 1 if self.use_tail else self.levels):
            self.dispatch(encoder, 'downsample', max(1, w >> mip), max(1, h >> mip),
                coarseLuminance=self.pyramid_view(mip - 1), lightnessOutput=self.pyramid_view(mip),
                linearSampler=self.sampler)
        self._weight_key = key
        self._result_key = None

    def prepare_result(self, encoder, hdr_source, exposure_ev, production=False):
        key = (self._weight_key, production)
        if key == self._result_key:
            return
        w, h = self.compact.width, self.compact.height
        if self.use_tail:
            self.dispatch(encoder, 'tail', 8, 8, fineLuminance=self.pyramid_view(self.tail_mip),
                reconstructionOutput=self.reconstructed.create_view(mip=self.tail_mip, mip_count=1),
                tailLevels=self.levels - self.tail_mip)
        fuse_fine = self.levels > 3 and (not self.use_tail or self.tail_mip >= 3)
        for mip in reversed(range(self.tail_mip if self.use_tail else self.levels)):
            if fuse_fine and mip in (1, 2):
                continue
            bindings = dict(fineLuminance=self.pyramid_view(mip),
                coarseLuminance=self.pyramid_view(min(mip + 1, self.levels - 1)),
                previousResult=self.base_lightness if mip == self.levels - 1 else
                    self.reconstructed.create_view(mip=mip + 1, mip_count=1),
                linearSampler=self.sampler, isCoarsest=mip == self.levels - 1)
            if mip:
                self.dispatch(encoder, 'reconstruct', max(1, w >> mip), max(1, h >> mip),
                    reconstructionOutput=self.reconstructed.create_view(mip=mip, mip_count=1), **bindings)
            else:
                if fuse_fine:
                    bindings.update(previousResult=self.reconstructed.create_view(mip=3, mip_count=1),
                        mip2Luminance=self.pyramid_view(2), mip3Luminance=self.pyramid_view(3))
                self.dispatch(encoder, 'finish_fused' if fuse_fine else 'finish', w, h,
                    compactSource=self.compact, compactOutput=self.residual,
                    baseLightness=self.base_lightness, **bindings)
        curve_bindings = (self.lookup_bindings if self.curve_mode == 'ue-film' else
            dict(self.curve.bindings(), fineLookup=self.lookup_bindings['fineLookup'], guided=True))
        self.dispatch(encoder, 'production' if production else 'apply', hdr_source.width, hdr_source.height,
            fullSource=hdr_source, averagedCoefficients=self.residual, lowResidual=self.pyramid_view(0),
            colorOutput=self.final_color,
            linearSampler=self.sampler, globalEV=exposure_ev, **curve_bindings,
            **({} if production else dict(fullExposureOutput=self.local_exposure, baseOutput=self.base_color)))
        self._result_key = key

    def record_processing(self, encoder, source, exposure_ev, highlight_ev=1.2, shadow_ev=1.2, sigma=.2):
        self._weight_key = self._result_key = None
        self.prepare_weights(encoder, source, exposure_ev, highlight_ev, shadow_ev, sigma)
        self.prepare_result(encoder, source, exposure_ev, production=True)
