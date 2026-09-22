import argparse
import math
from pathlib import Path
import time

import slangpy as spy

from tone_mapper import ROOT, ToneMapper, load_exr, save_png

VIEW_NAMES = ["fusion", "compare", "local-exposure"]
VIEW_LABELS = ["Fusion result", "Compare: original | fusion", "Local exposure (EV)"]
VIEW_HELP = ["HDR x global exposure x local exposure -> ACES -> sRGB",
             "Left: original | Right: fusion (same image coordinates)",
             "Black -6 EV | Gray 0 EV | White +6 EV"]

DEFAULT_CONTRAST_SCALE = 0.8  # UE project-template setting: 1.2 EV bracket.


def contrast_scale_to_ev(scale):
    """UE Fusion semantics: 1 = no bracket, 0 = six-stop bracket."""
    if not math.isfinite(scale) or not 0 <= scale <= 1:
        raise ValueError("Contrast Scale must be finite and between 0 and 1")
    return 6.0 * (1.0 - scale)


class Viewer:
    def __init__(self, args):
        self.args = args
        self.device = spy.Device(type=getattr(spy.DeviceType, args.device), enable_hot_reload=False)
        self.mapper = ToneMapper(self.device, args.levels)
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
        self.surface.configure(width=self.window.width, height=self.window.height,
                               format=spy.Format.rgba8_unorm, vsync=True)
        self.ui = spy.ui.Context(self.device)
        panel = spy.ui.Window(self.ui.screen, "Local Exposure", spy.float2(12, 12), spy.float2(480, 385))
        self.label = spy.ui.Text(panel, self.assets[self.index].name)
        spy.ui.ComboBox(panel, "View", items=VIEW_LABELS,
                        value=self.view_mode, callback=self.set_view)
        self.view_help = spy.ui.Text(panel, VIEW_HELP[self.view_mode])
        self.slider = spy.ui.SliderFloat(panel, "Exposure (EV)", min=-16, max=16,
                                        value=self.exposure, callback=self.set_exposure)
        spy.ui.SliderFloat(panel, "Highlight Contrast Scale", min=0, max=1,
                           value=self.highlight_contrast, callback=self.set_highlights)
        spy.ui.SliderFloat(panel, "Shadow Contrast Scale", min=0, max=1,
                           value=self.shadow_contrast, callback=self.set_shadows)
        spy.ui.Text(panel, "Scale 1: no adjustment | Scale 0: 6 EV bracket")
        self.exposure_info = spy.ui.Text(panel, "")
        self.update_exposure_ui()
        self.sigma_slider = spy.ui.SliderFloat(panel, "Weight sigma (UE exp2)", min=0.02, max=0.8, value=self.sigma,
                           callback=lambda value: setattr(self, "sigma", value))
        spy.ui.Button(panel, "Reset exposure", callback=self.reset_exposure)
        spy.ui.Button(panel, "Previous image", callback=lambda: self.change_image(-1))
        spy.ui.Button(panel, "Next image", callback=lambda: self.change_image(1))
        spy.ui.Button(panel, "Reload shader (F5)", callback=self.reload)
        spy.ui.Button(panel, "Save PNG (F2)", callback=self.save)
        self.status = spy.ui.Text(panel, "ACES Filmic + sRGB")
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
        self.exposure_info.text = (
            f"Darker {self.exposure - self.highlight_ev:+.1f} EV | "
            f"Base {self.exposure:+.1f} EV | Brighter {self.exposure + self.shadow_ev:+.1f} EV"
        )

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
            self.surface.configure(width=width, height=height, format=spy.Format.rgba8_unorm, vsync=True)
        else:
            self.surface.unconfigure()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="SlangPy HDR viewer with ACES Filmic tone mapping")
    parser.add_argument("--image", type=Path, default=ROOT / "Assets" / "veranda_4k.exr")
    parser.add_argument("--exposure", type=float, default=0.0, help="Exposure compensation in EV")
    parser.add_argument("--view", choices=VIEW_NAMES, default="fusion")
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
    parser.add_argument("--device", choices=["automatic", "d3d12", "vulkan"], default="automatic")
    parser.add_argument("--headless", action="store_true", help="Render a PNG without a window")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs" / "preview.png")
    parser.add_argument("--frames", type=int, default=0, help="Close viewer after N frames (0: unlimited)")
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
    return args


def main():
    Viewer(parse_args()).run()


if __name__ == "__main__":
    main()
