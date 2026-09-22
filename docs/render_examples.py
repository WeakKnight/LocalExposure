"""Regenerate README comparisons: .venv/Scripts/python.exe docs/render_examples.py."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import slangpy as spy
from tone_mapper import ROOT, ToneMapper, load_exr, save_png


def main():
    device = spy.Device(enable_hot_reload=False)
    mapper = ToneMapper(device)
    for scene, ev in [('sundowner_deck', -2.0), ('veranda', -1.0)]:
        source = load_exr(device, ROOT / 'Assets' / f'{scene}_4k.exr')
        output = mapper.create_output(1200, 600)
        for label, bracket in [('before', 0.0), ('after', 3.0)]:
            # Zero brackets are identity: global exposure + ACES only.
            encoder = device.create_command_encoder()
            mapper.execute(encoder, source, output, ev,
                           highlight_ev=bracket, shadow_ev=bracket, sigma=0.2)
            device.submit_command_buffer(encoder.finish())
            save_png(output, ROOT / 'docs' / 'images' / f'{scene}-{label}.png')
    device.wait()


if __name__ == '__main__':
    main()
