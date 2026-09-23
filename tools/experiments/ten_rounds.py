from pathlib import Path
import sys, json, subprocess, time
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.mobile_profile import export_pass,compiler,aoc_sections,run
OUT=ROOT/'outputs/optimization10'
OUT.mkdir(parents=True,exist_ok=True)
BASE=(ROOT/'tests/fixtures/guided_before_ten_rounds.slang').read_text()
DISPLAY=(ROOT/'tests/fixtures/tonemap_before_ten_rounds.slang').read_text()
AOC=ROOT/'.tools/mobile/aoc-7.0.15/installed/aoc.exe'
SLANG=compiler()

def section(src,entry):
    start=src.index('void '+entry+'(')
    end=src.find('\nTexture2D',start)
    return src[start:] if end<0 else src[start:end]

def flatten(src,entry):
    old=section(src,entry)
    new=old.replace('for (int y = -2; y <= 2; ++y)\n        for (int x = -2; x <= 2; ++x)',
                    'for (uint tap = 0; tap < 25; ++tap)')
    if entry=='fit_coefficients':
        new=new.replace('uint index = (localID.y + y + 2) * 12 + localID.x + x + 2;',
                        'uint index = (localID.y + tap / 5) * 12 + localID.x + tap % 5;')
    else:
        new=new.replace('(localID.y + y + 2) * 12 + localID.x + x + 2',
                        '(localID.y + tap / 5) * 12 + localID.x + tap % 5')
    return src.replace(old,new)

def padding(src,entry,tile):
    old=section(src,entry)
    new=old.replace(tile+'[i]',tile+'[(i / 12) * 13 + i % 12]')
    new=new.replace('(localID.y + 2) * 12','(localID.y + 2) * 13')
    new=new.replace('(localID.y + y + 2) * 12','(localID.y + y + 2) * 13')
    return src.replace(old,new).replace(tile+'[144]',tile+'[156]')

def row_load(src,entry):
    old=section(src,entry)
    new=old.replace('for (uint i = lane; i < 144; i += 64)',
         'for (uint ty = localID.y; ty < 12; ty += 8)\n    for (uint tx = localID.x; tx < 12; tx += 8)')
    new=new.replace('int2(i % 12, i / 12)','int2(tx, ty)')
    new=new.replace('fitTile[i]','fitTile[ty * 12 + tx]').replace('coefficientTile[i]','coefficientTile[ty * 12 + tx]')
    return src.replace(old,new)

variants=[]
variants.append(('flat_fit','guided','fit_coefficients',flatten(BASE,'fit_coefficients')))
variants.append(('flat_average','guided','average_coefficients',flatten(BASE,'average_coefficients')))
variants.append(('packed_half_products','guided','fit_coefficients',BASE.replace(
    'meanG += g; meanE += e; meanGG += float(g*g); meanGE += float(g*e);',
    'half2 products = half2(g, g) * half2(g, e);\n            meanG += g; meanE += e; meanGG += float(products.x); meanGE += float(products.y);')))
variants.append(('padded_fit','guided','fit_coefficients',padding(BASE,'fit_coefficients','fitTile')))
variants.append(('padded_average','guided','average_coefficients',padding(BASE,'average_coefficients','coefficientTile')))
variants.append(('row_load_fit','guided','fit_coefficients',row_load(BASE,'fit_coefficients')))
variants.append(('row_load_average','guided','average_coefficients',row_load(BASE,'average_coefficients')))
variants.append(('hoist_reduction_y','guided','reduce_source',BASE.replace(
    'for (uint y = 0; y < reductionRows; ++y)\n        for',
    'for (uint y = 0; y < reductionRows; ++y)\n    {\n        float v = (float(tid.y) + (float(y) + 0.5) / 4.0) / float(h);\n        for').replace(
    '(float2(tid.xy) + (float2(x, y) + 0.5) / 4.0) / float2(w, h)',
    'float2((float(tid.x) + (float(x) + 0.5) / 4.0) / float(w), v)').replace(
    '    reducedOutput[tid.xy] = sum / 16.0;', '    }\n    reducedOutput[tid.xy] = sum / 16.0;')))
variants.append(('exclusive_display_sample','tonemap','compute_main',DISPLAY.replace(
    'half3 mapped = half3(finalColor.SampleLevel(linearSampler, uv, 0).rgb);', 'half3 mapped;').replace(
    'mapped = half3(source.SampleLevel(linearSampler, uv, 0).rgb);',
    'mapped = half3(source.SampleLevel(linearSampler, uv, 0).rgb);\n    else\n        mapped = half3(finalColor.SampleLevel(linearSampler, uv, 0).rgb);')))
variants.append(('identity_tonemap_reuse','guided','apply_exposure',BASE.replace(
    'baseOutput[tid.xy] = half4(half3(toneOperator(color)), half(1.0));\n    colorOutput[tid.xy] = half4(half3(toneOperator(color * float(multiplier))), half(1.0));',
    'half4 base = half4(half3(toneOperator(color)), half(1.0));\n    baseOutput[tid.xy] = base;\n    if (multiplier == half(1.0)) colorOutput[tid.xy] = base;\n    else colorOutput[tid.xy] = half4(half3(toneOperator(color * float(multiplier))), half(1.0));')))

lo=int(sys.argv[1]); hi=int(sys.argv[2])
for index,(name,module,entry,src) in enumerate(variants,1):
    if not lo<=index<=hi: continue
    dest=OUT/f'{index:02d}-{name}';dest.mkdir(exist_ok=True)
    path=ROOT/f'shaders/{module}.slang'
    prior=path.read_text()
    try:
        path.write_text(src)
        (dest/f'{module}.slang').write_text(src)
        export=export_pass(SLANG,module,entry,dest)
        cmd=[AOC,'-api=Vulkan','-arch=a730','-entry_point_cs',entry,'-cs',dest/'shader.spv','-dump=all']
        raw=run(cmd,dest/'aoc.log',cwd=dest)
        if 'Compilation succeeded.' not in raw:raise RuntimeError('AOC failed')
        test=subprocess.run([sys.executable,'-m','unittest','test_fit','test_average','test_reduction','test_rounds'],cwd=ROOT,capture_output=True,text=True)
        (dest/'tests.log').write_text(test.stdout+test.stderr)
        result=dict(round=index,name=name,entry=entry,bitwise_tests_pass=test.returncode==0,
                    sections=aoc_sections(raw),export=export)
        (dest/'result.json').write_text(json.dumps(result,indent=2))
        s=result['sections']['Main Shader Stats']
        print(index,name,'tests',test.returncode,'instructions',s['Total instruction count'],'regs',s['Overall register footprint per shader instance'],'scratch',s['Scratch memory usage per shader instance'],flush=True)
    finally:
        path.write_text(prior)
