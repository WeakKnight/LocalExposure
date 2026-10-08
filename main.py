import argparse
from dataclasses import replace
import math
from pathlib import Path
import time

import slangpy as spy

from tone_mapper import ROOT, ToneMapper, load_exr, save_png
from fine_residual import FineResidualToneMapper
from ue_local_exposure import UEParameters, UnrealLocalExposure

METHOD_NAMES = ['bart', 'ue-fusion', 'ue-bilateral']
METHOD_LABELS = ['Bart Fusion', 'UE 5.8 Fusion', 'UE 5.8 Bilateral Grid']


def create_mapper(device, args):
    if args.method == 'bart':
        settings = dict(curve_mode=args.fusion_curve, film_parameters=args.ue_parameters)
        return (FineResidualToneMapper(device, args.levels, **settings) if args.fusion_scale == 4
                else ToneMapper(device, args.levels, fusion_scale=1, **settings))
    return UnrealLocalExposure(device, args.method, args.levels, args.ue_parameters)

VIEW_NAMES = ["fusion", "compare", "local-exposure"]
VIEW_LABELS = ["Local exposure result", "Compare: global | local", "Local exposure (EV)"]
VIEW_HELP = ["HDR x global exposure x local exposure -> ACES -> sRGB",
             "Left: global only | Right: local exposure (same coordinates)",
             "Black -6 EV | Gray 0 EV | White +6 EV"]

DEFAULT_CONTRAST_SCALE = 0.8  # UE project-template setting: 1.2 EV bracket.


def contrast_scale_to_ev(scale):
    """UE Fusion semantics: 1 = no bracket, 0 = six-stop bracket."""
    if not math.isfinite(scale) or not 0 <= scale <= 1:
        raise ValueError("Contrast Scale must be finite and between 0 and 1")
    return 6.0 * (1.0 - scale)


def select_surface_format(formats):
    # The viewer output already contains sRGB codes; avoid encoding them again.
    # RGBA preserves the existing path; Metal surfaces typically require BGRA.
    for format in (spy.Format.rgba8_unorm, spy.Format.bgra8_unorm):
        if format in formats:
            return format
    raise RuntimeError(f"Viewer requires an RGBA8 or BGRA8 UNORM surface; supported formats: {formats}")


class Viewer:
    def __init__(self, args):
        self.args = args
        self.device = spy.Device(type=getattr(spy.DeviceType, args.device), enable_hot_reload=False)
        self.mapper = create_mapper(self.device, args)
        self.assets = sorted((ROOT / "Assets").glob("*.exr"))
        if args.image not in self.assets:
            self.assets.insert(0, args.image)
        self.index = self.assets.index(args.image)
        self.source = load_exr(self.device, args.image)
        self.exposure = args.exposure
        self.view_mode = VIEW_NAMES.index(args.view)
        self.sigma = args.sigma
        self.highlight_contrast = args.highlight_contrast
        self.shadow_contrast = args.shadow_contrast
        self.output = None
        print(f"Loaded {args.image.name}: {self.source.width} x {self.source.height}", flush=True)

    def render(self, width, height):
        if self.output is None or (self.output.width, self.output.height) != (width, height):
            self.output = self.mapper.create_output(width, height)
        encoder = self.device.create_command_encoder()
        self.mapper.execute(encoder, self.source, self.output, self.exposure,
                            view_mode=self.view_mode, highlight_ev=self.highlight_ev,
                            shadow_ev=self.shadow_ev, sigma=self.sigma)
        return encoder

    def run(self):
        if self.args.headless:
            encoder = self.render(self.args.width, self.args.height)
            self.device.submit_command_buffer(encoder.finish())
            save_png(self.output, self.args.output)
            return
        self.window = spy.Window(width=self.args.width, height=self.args.height,
                                 title="Local Exposure | ACES Filmic", resizable=True)
        self.surface = self.device.create_surface(self.window)
        self.resize(self.window.width, self.window.height)
        self.ui = spy.ui.Context(self.device)
        panel = spy.ui.Window(self.ui.screen, "Local Exposure", spy.float2(12, 12), spy.float2(480, 560))
        self.label = spy.ui.Text(panel, self.assets[self.index].name)
        self.method_selector = spy.ui.ComboBox(panel, "Algorithm", items=METHOD_LABELS,
            value=METHOD_NAMES.index(self.args.method), callback=self.set_method)
        spy.ui.ComboBox(panel, "View", items=VIEW_LABELS,
                        value=self.view_mode, callback=self.set_view)
        self.view_help = spy.ui.Text(panel, VIEW_HELP[self.view_mode])
        self.resolution_selector = spy.ui.ComboBox(panel, "Bart resolution", items=["1/4 x 1/4 (fine residual)", "Full resolution reference"],
                        value=0 if self.args.fusion_scale == 4 else 1, callback=self.set_resolution)
        self.curve_selector = spy.ui.ComboBox(panel, 'Bart curve',
            items=['Calibrated Z (LUT)', 'UE film (analytic)'],
            value=0 if self.args.fusion_curve == 'z' else 1, callback=self.set_curve)
        self.slider = spy.ui.SliderFloat(panel, "Exposure (EV)", min=-16, max=16,
                                        value=self.exposure, callback=self.set_exposure)
        spy.ui.SliderFloat(panel, "Highlight Contrast Scale", min=0, max=1,
                           value=self.highlight_contrast, callback=self.set_highlights)
        spy.ui.SliderFloat(panel, "Shadow Contrast Scale", min=0, max=1,
                           value=self.shadow_contrast, callback=self.set_shadows)
        self.scale_help = spy.ui.Text(panel, "")
        self.exposure_info = spy.ui.Text(panel, "")
        self.update_exposure_ui()
        self.sigma_slider = spy.ui.SliderFloat(panel, "Weight sigma (UE exp2)", min=0.02, max=0.8, value=self.sigma,
                           callback=lambda value: setattr(self, "sigma", value))
        self.bilateral_controls = [
            spy.ui.SliderFloat(panel, label, min=low, max=high, value=getattr(self.args.ue_parameters, field),
                callback=lambda value, name=field: self.set_ue_parameter(name, value))
            for label, field, low, high in [
                ('Detail strength', 'detail_strength', 0, 3), ('Blurred luminance blend', 'blurred_blend', 0, 1),
                ('Blur kernel (%)', 'blur_percent', 0, 100), ('Middle grey bias (EV)', 'middle_grey_bias', -6, 6),
                ('Highlight threshold (EV)', 'highlight_threshold', 0, 8), ('Shadow threshold (EV)', 'shadow_threshold', 0, 8),
                ('Highlight threshold strength', 'highlight_threshold_strength', 0, 1),
                ('Shadow threshold strength', 'shadow_threshold_strength', 0, 1)]]
        spy.ui.Button(panel, "Reset exposure", callback=self.reset_exposure)
        spy.ui.Button(panel, "Previous image", callback=lambda: self.change_image(-1))
        spy.ui.Button(panel, "Next image", callback=lambda: self.change_image(1))
        spy.ui.Button(panel, "Reload shader (F5)", callback=self.reload)
        spy.ui.Button(panel, "Save PNG (F2)", callback=self.save)
        self.status = spy.ui.Text(panel, "ACES Filmic + sRGB")
        self.update_method_controls()
        self.window.on_keyboard_event = self.on_key
        self.window.on_mouse_event = self.ui.handle_mouse_event
        self.window.on_resize = self.resize
        frames = 0
        while not self.window.should_close():
            self.window.process_events()
            if self.window.should_close():
                break
            if not self.surface.config:
                time.sleep(0.02)
                continue
            target = self.surface.acquire_next_image()
            if target is None:
                continue
            encoder = self.render(target.width, target.height)
            encoder.blit(target, self.output)
            self.ui.begin_frame(self.window.width, self.window.height)
            self.ui.end_frame(target, encoder)
            self.device.submit_command_buffer(encoder.finish())
            del target
            self.surface.present()
            frames += 1
            if self.args.frames and frames >= self.args.frames:
                break
        self.device.wait()

    def set_exposure(self, value):
        self.exposure = value
        self.update_exposure_ui()

    def set_method(self, value):
        previous = self.args.method
        try:
            self.device.wait()
            self.args.method = METHOD_NAMES[value]
            mapper = create_mapper(self.device, self.args)
            self.mapper = mapper
            self.update_method_controls()
            self.update_exposure_ui()
            self.status.text = METHOD_LABELS[value] + ' | ACES Filmic + sRGB'
        except Exception as exc:
            self.args.method = previous
            self.method_selector.value = METHOD_NAMES.index(previous)
            self.status.text = 'Algorithm load failed; previous algorithm retained'
            print(exc, flush=True)

    def set_curve(self, value):
        previous = self.args.fusion_curve
        try:
            self.device.wait()
            self.args.fusion_curve = ['z', 'ue-film'][value]
            self.mapper = create_mapper(self.device, self.args)
            self.status.text = 'Bart curve: ' + self.args.fusion_curve
        except Exception as exc:
            self.args.fusion_curve = previous
            self.curve_selector.value = 0 if previous == 'z' else 1
            self.status.text = 'Curve change failed; previous curve retained'
            print(exc, flush=True)

    def set_resolution(self, value):
        previous = self.args.fusion_scale
        try:
            self.device.wait()
            self.args.fusion_scale = 4 if value == 0 else 1
            if self.args.method == 'bart':
                mapper = create_mapper(self.device, self.args)
                mapper.curve = self.mapper.curve
                self.mapper = mapper
                self.status.text = 'Bart fine residual' if value == 0 else 'Bart full-resolution reference'
        except Exception as exc:
            self.args.fusion_scale = previous
            self.resolution_selector.value = 0 if previous == 4 else 1
            self.status.text = 'Resolution change failed; previous algorithm retained'
            print(exc, flush=True)

    def set_ue_parameter(self, name, value):
        self.args.ue_parameters = replace(self.args.ue_parameters, **{name: value})
        if self.args.method != 'bart':
            self.mapper.parameters = self.args.ue_parameters

    def update_method_controls(self):
        self.resolution_selector.visible = self.args.method == 'bart'
        self.curve_selector.visible = self.args.method == 'bart'
        self.sigma_slider.visible = self.args.method == 'bart'
        for control in self.bilateral_controls:
            control.visible = self.args.method == 'ue-bilateral'
        self.scale_help.text = ('Scale 1: preserve base contrast | Scale 0: flatten base contrast'
            if self.args.method == 'ue-bilateral' else 'Scale 1: no bracket | Scale 0: 6 EV bracket')

    def set_highlights(self, value):
        self.highlight_contrast = value
        self.update_exposure_ui()

    def set_shadows(self, value):
        self.shadow_contrast = value
        self.update_exposure_ui()

    @property
    def highlight_ev(self):
        return contrast_scale_to_ev(self.highlight_contrast)

    @property
    def shadow_ev(self):
        return contrast_scale_to_ev(self.shadow_contrast)

    def update_exposure_ui(self):
        self.exposure_info.text = (f'Highlight {self.highlight_contrast:.2f} | Shadow {self.shadow_contrast:.2f}'
            if self.args.method == 'ue-bilateral' else (
            f"Darker {self.exposure - self.highlight_ev:+.1f} EV | "
            f"Base {self.exposure:+.1f} EV | Brighter {self.exposure + self.shadow_ev:+.1f} EV"
        ))

    def set_view(self, value):
        self.view_mode = value
        self.view_help.text = VIEW_HELP[value]

    def reset_exposure(self):
        self.exposure = 0.0
        self.slider.value = 0.0
        self.update_exposure_ui()

    def change_image(self, step):
        index = (self.index + step) % len(self.assets)
        try:
            source = load_exr(self.device, self.assets[index])
            self.device.wait()
            self.source, self.index = source, index
            self.label.text = self.assets[index].name
            self.status.text = f"{source.width} x {source.height} | ACES Filmic + sRGB"
        except Exception as exc:
            self.status.text = "Image load failed; see console"
            print(exc, flush=True)

    def reload(self):
        try:
            self.device.wait()
            self.mapper.reload()
            self.status.text = "Shader reloaded"
        except Exception as exc:
            self.status.text = "Compile failed; previous shader retained"
            print(exc, flush=True)

    def save(self):
        if self.output is not None:
            save_png(self.output, self.args.output)
            self.status.text = f"Saved {self.args.output.name}"

    def on_key(self, event):
        if self.ui.handle_keyboard_event(event):
            return
        if event.type == spy.KeyboardEventType.key_press:
            if event.key == spy.KeyCode.escape:
                self.window.close()
            elif event.key == spy.KeyCode.f5:
                self.reload()
            elif event.key == spy.KeyCode.f2:
                self.save()

    def resize(self, width, height):
        self.device.wait()
        if width > 0 and height > 0:
            self.surface.configure(width=width, height=height,
                                   format=select_surface_format(self.surface.info.formats), vsync=True)
        else:
            self.surface.unconfigure()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="SlangPy HDR viewer with ACES Filmic tone mapping")
    parser.add_argument("--image", type=Path, default=ROOT / "Assets" / "veranda_4k.exr")
    parser.add_argument("--exposure", type=float, default=0.0, help="Exposure compensation in EV")
    parser.add_argument("--view", choices=VIEW_NAMES, default="fusion")
    parser.add_argument('--method', choices=METHOD_NAMES, default='bart', help='Local exposure algorithm')
    parser.add_argument('--fusion-curve', choices=['z', 'ue-film'], default='z',
                        help='Bart curve: calibrated Z LUT or analytic UE film/fixed inverse; UE film flags apply')
    parser.add_argument("--fusion-scale", type=int, choices=[1, 4], default=4,
                        help="Fusion resolution divisor per axis: 4 fine residual (default), 1 full reference")
    parser.add_argument("--sigma", type=float, default=0.2, help="UE exp2 weight width (0.02 to 0.8; default 0.2)")
    parser.add_argument("--levels", type=int, default=16, help="Maximum fusion levels, capped by shorter side (UE default: 16)")
    highlight_group = parser.add_mutually_exclusive_group()
    highlight_group.add_argument("--highlight-contrast", type=float,
                                help="UE Fusion Highlight Contrast Scale (0..1; default 0.8 = -1.2 EV)")
    highlight_group.add_argument("--highlights", type=float,
                                help="Legacy: darker bracket in EV (0..6), converted to Contrast Scale")
    shadow_group = parser.add_mutually_exclusive_group()
    shadow_group.add_argument("--shadow-contrast", type=float,
                             help="UE Fusion Shadow Contrast Scale (0..1; default 0.8 = +1.2 EV)")
    shadow_group.add_argument("--shadows", type=float,
                             help="Legacy: brighter bracket in EV (0..6), converted to Contrast Scale")
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=810)
    parser.add_argument("--device", choices=["automatic", "d3d12", "vulkan", "metal"], default="automatic")
    parser.add_argument("--headless", action="store_true", help="Render a PNG without a window")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs" / "preview.png")
    parser.add_argument("--frames", type=int, default=0, help="Close viewer after N frames (0: unlimited)")
    ue = parser.add_argument_group('UE 5.8 local exposure')
    ue.add_argument('--ue-profile', choices=['desktop', 'mobile'], default='desktop', help='UE input/blur resolution graph')
    ue.add_argument('--ue-storage', choices=['native', 'fp32'], default='native', help='UE texture storage or FP32 precision control')
    ue.add_argument('--ue-luminance-method', choices=['uniform', 'rec709', 'ntsc'], default='uniform')
    for flag, default in [('histogram-min', -8), ('histogram-max', 4), ('pre-exposure', 1),
                          ('grey-multiplier', 1), ('middle-grey-bias', 0), ('detail-strength', 1),
                          ('blurred-blend', .6), ('blur-percent', 50), ('highlight-threshold', 0),
                          ('shadow-threshold', 0), ('highlight-threshold-strength', 1),
                          ('shadow-threshold-strength', 1), ('target-luminance', .5),
                          ('film-slope', .88), ('film-toe', .55), ('film-shoulder', .26),
                          ('film-black-clip', 0), ('film-white-clip', .04)]:
        ue.add_argument('--ue-' + flag, type=float, default=default)
    args = parser.parse_args(argv)
    if args.levels < 1:
        parser.error("Levels must be positive")
    args.image = args.image.resolve()
    if not args.image.is_file():
        parser.error(f"Image does not exist: {args.image}")
    if args.width <= 0 or args.height <= 0 or args.frames < 0:
        parser.error("Dimensions must be positive and frames must be nonnegative")
    if not math.isfinite(args.exposure) or not -16 <= args.exposure <= 16:
        parser.error("Exposure must be finite and between -16 and 16 EV")
    if any(v is not None and (not math.isfinite(v) or not 0 <= v <= 6) for v in (args.highlights, args.shadows)):
        parser.error("Highlights and shadows offsets must be finite and between 0 and 6 EV")
    for name, legacy in (("highlight_contrast", args.highlights), ("shadow_contrast", args.shadows)):
        value = getattr(args, name)
        if value is None:
            value = DEFAULT_CONTRAST_SCALE if legacy is None else 1.0 - legacy / 6.0
        try:
            contrast_scale_to_ev(value)
        except ValueError as exc:
            parser.error(str(exc))
        setattr(args, name, value)
    if not math.isfinite(args.sigma) or not 0.02 <= args.sigma <= 0.8:
        parser.error("Sigma must be finite and between 0.02 and 0.8")
    try:
        args.ue_parameters = UEParameters(**{name[3:]: value for name, value in vars(args).items() if name.startswith('ue_')})
    except ValueError as exc:
        parser.error(str(exc))
    return args


def main():
    Viewer(parse_args()).run()


if __name__ == "__main__":
    main()
