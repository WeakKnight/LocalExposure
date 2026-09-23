"""Check compute measurements after real graphics work on the same GPU queue."""
import argparse,json,shutil
from pathlib import Path
from .benchmark import ADB,NDK,TOOLS,run,select_device,stats
from .prepare import sha

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('bundle',type=Path);ap.add_argument('--out',required=True,type=Path)
    args=ap.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    bundle=args.bundle.resolve();manifest=json.loads((bundle/'manifest.json').read_text())
    original=manifest.get('unfused_passes',manifest['passes'])
    context=next(p.copy() for p in original if p['entry']=='baseline_fragment')
    context.update(label='graphics_context',attachment='context_color',baseline=True)
    manifest['passes'].append(context)
    manifest['resources'].append(dict(name='context_color',width=manifest['width'],height=manifest['height'],levels=1,format=43,format_name='rgba8_srgb',bpp=4,one_d=False,dump=False,attachment=True))
    deploy=out/'deploy';deploy.mkdir()
    for p in bundle.iterdir():
        if p.suffix=='.spv' or (p.suffix=='.bin' and not p.name.endswith(('.reference.bin','.device.bin','.phone-reference.bin'))):shutil.copy2(p,deploy/p.name)
    (deploy/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    clang=NDK/'toolchains/llvm/prebuilt/windows-x86_64/bin/clang++.exe'
    cmd=[clang,'--target=aarch64-linux-android29','-std=c++17','-O2','-static-libstdc++','-I',TOOLS,Path(__file__).with_suffix('.cpp'),'-lvulkan','-o',deploy/'context-audit']
    run(cmd)
    adb=[ADB,'-s',select_device(ADB)];remote='/data/local/tmp/local-exposure-context'
    run([*adb,'shell','mkdir','-p',remote]);run([*adb,'push',str(deploy)+'/.',remote])
    (out/'metadata.json').write_text(json.dumps(dict(command=list(map(str,cmd)),runner_sha256=sha(deploy/'context-audit'),manifest_sha256=sha(deploy/'manifest.json')),indent=2))
    print(run([*adb,'shell',f'cd {remote} && chmod 755 context-audit && ./context-audit'],timeout=240),flush=True)
    run([*adb,'pull',remote+'/context.json',out/'context.json'])
    run([*adb,'pull',remote+'/final.device.bin',out/'final.device.bin'])
    assert (out/'final.device.bin').read_bytes()==(bundle/'final.device.bin').read_bytes(),'Audit changed final image'
    raw=json.loads((out/'context.json').read_text());summary={}
    for mode in [False,True]:
        data={kind:stats([v for b in raw['blocks'] if b['preceding_graphics']==mode and b['kind']==kind for v in b['gpu_ms']]) for kind in ['fusion','baseline']}
        data['increment_ms']=data['fusion']['median']-data['baseline']['median'];summary[str(mode)]=data
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
