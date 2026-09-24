"""Build and run a Vulkan tile-memory capability probe on the connected phone."""
import argparse
import json
from pathlib import Path
from .benchmark import ADB, NDK, TOOLS, run, select_device
from .prepare import sha


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--serial')
    ap.add_argument('--api', choices=['1.2', 'max'], default='1.2')
    ap.add_argument('--surface', action='store_true', help='Enable Android surface instance extensions')
    ap.add_argument('--custom-driver', type=Path, help='Extracted AdrenoTools driver directory')
    args = ap.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).with_suffix('.cpp')
    binary = out / 'tile-memory-probe'
    clang = NDK / 'toolchains/llvm/prebuilt/windows-x86_64/bin/clang++.exe'
    link = ['-lvulkan']
    defines = []
    if args.custom_driver:
        from . import custom_driver
        defines = ['-DLOCAL_EXPOSURE_CUSTOM_DRIVER']
        link = custom_driver.link_args() + ['-landroid', '-llog']
    run([clang, '--target=aarch64-linux-android29', '-std=c++17', '-O2',
         '-static-libstdc++', *defines, '-I', TOOLS, source, *link, '-o', binary])
    adb = [ADB, '-s', select_device(ADB, args.serial)]
    remote = '/data/local/tmp/local-exposure-tile-probe'
    run([*adb, 'push', binary, remote])
    mode = 'surface' if args.surface else 'headless'
    extra = ''
    if args.custom_driver:
        library, files = custom_driver.driver_files(args.custom_driver)
        root = '/data/local/tmp/le-custom-driver'
        run([*adb, 'shell', 'mkdir', '-p', root+'/hooks', root+'/driver'])
        for p in (custom_driver.BUILD/'src/hook').glob('*.so'):
            run([*adb, 'push', p, root+'/hooks/'+p.name])
        for p in files:
            run([*adb, 'push', p, root+'/driver/'+p.name])
        # Driver metadata must not become shell syntax.
        import shlex
        extra = f' {root}/hooks/ {root}/driver/ {shlex.quote(library)}'
    raw = run([*adb, 'shell', f'chmod 755 {remote} && {remote} {args.api} {mode}{extra}'])
    devices = json.loads(raw)
    report = dict(devices=devices, source_sha256=sha(source), binary_sha256=sha(binary),
                  fingerprint=run([*adb, 'shell', 'getprop ro.build.fingerprint']).strip())
    if args.custom_driver:
        report['custom_driver'] = custom_driver.provenance(args.custom_driver)
    (out / 'capabilities.json').write_text(json.dumps(report, indent=2)+'\n')
    for d in devices:
        print(json.dumps({k: v for k, v in d.items() if k != 'extensions'}, indent=2))


if __name__ == '__main__':
    main()
