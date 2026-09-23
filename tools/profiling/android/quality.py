"""Explicit approximation presets and fixed preliminary image-quality gates."""
import numpy as np

from .variants import VARIANTS



def image_quality(reference, actual):
    # Display-encoded RGB errors in 8-bit code values; alpha is not image quality.
    a=np.asarray(reference,dtype=np.float64)[...,:3]
    b=np.asarray(actual,dtype=np.float64)[...,:3]
    if a.shape!=b.shape or a.size==0: raise ValueError('Mismatched/empty image comparison')
    finite=bool(np.isfinite(a).all() and np.isfinite(b).all())
    if not finite: return dict(accepted=False,finite=False)
    error=abs(a-b)
    worst_pixel=error.max(axis=-1)
    result=dict(finite=True,rmse_codes=float(np.sqrt(np.mean(error**2))),
                p99_codes=float(np.percentile(error,99)),max_codes=float(error.max()),
                fraction_pixels_over4=float(np.mean(worst_pixel>4)))
    result['thresholds']=dict(rmse_codes=.75,p99_codes=3,max_codes=12,fraction_pixels_over4=.001)
    result['accepted']=all(result[k]<=v for k,v in result['thresholds'].items())
    result['note']='Preliminary numerical gate, not proof of perceptual equivalence; multi-scene and edge inspection still required.'
    return result


def save_comparison(bundle, manifest):
    from PIL import Image, ImageDraw
    from pathlib import Path
    bundle=Path(bundle)
    w,h=manifest['width'],manifest['height']
    a=np.fromfile(bundle/'final.phone-reference.bin',np.uint8).reshape(h,w,4)[...,:3]
    b=np.fromfile(bundle/'final.device.bin',np.uint8).reshape(h,w,4)[...,:3]
    error=abs(a.astype(np.int16)-b.astype(np.int16))
    images=[a,b,np.minimum(error*8,255).astype(np.uint8)]
    labels=['Original (same phone)','Candidate','Absolute difference x8']
    tile_w=640;tile_h=round(h*tile_w/w)
    sheet=Image.new('RGB',(tile_w*3,tile_h+28),(25,25,25))
    draw=ImageDraw.Draw(sheet)
    for i,(pixels,label) in enumerate(zip(images,labels)):
        sheet.paste(Image.fromarray(pixels).resize((tile_w,tile_h)),(i*tile_w,28))
        draw.text((i*tile_w+8,7),label,fill='white')
    sheet.save(bundle.parent/'comparison.png')
    y,x=np.unravel_index(error.max(axis=-1).argmax(),(h,w))
    x0=max(0,min(w-192,int(x)-96));y0=max(0,min(h-192,int(y)-96))
    crop=Image.new('RGB',(192*3,220),(25,25,25));draw=ImageDraw.Draw(crop)
    for i,(pixels,label) in enumerate(zip(images,labels)):
        crop.paste(Image.fromarray(pixels[y0:y0+192,x0:x0+192]),(i*192,28))
        draw.text((i*192+4,7),label,fill='white')
    crop.save(bundle.parent/'worst-crop.png')
