"""Desktop same-backend spatial and temporal stress screening for compact candidates."""
import argparse,json
from pathlib import Path
import numpy as np
import slangpy as spy
from tone_mapper import ToneMapper,create_hdr_texture,ROOT
from .quality import VARIANTS,image_quality

def codes(linear):
    x=np.maximum(linear[...,:3],0)
    srgb=np.where(x<=.0031308,x*12.92,1.055*x**(1/2.4)-.055)
    return np.rint(np.clip(srgb,0,1)*255).astype(np.uint8)

class Candidate:
    def __init__(self,device,mapper,variant):
        self.device,self.mapper,self.config=device,mapper,dict(VARIANTS[variant])
        if self.config.get('residual_snorm'):
            # Every lightness lies in [0,max_lightness]; normalized differences
            # and their Gaussian averages therefore remain representable in SNORM.
            self.config['residual_scale'] = 1.0 / max(1.0, mapper.curve.max_lightness)
        mapping={'PACKED_HALF_COEFFICIENTS':('packed_half_coefficients',False),'COEFF_PAD':('coefficient_padding',0),'GUIDED_INTERIOR_FIT':('guided_interior_fit',False),'SHARED_INPUT_LOG':('shared_input_log',False),'GATHER_QUAD_LOG':('gather_quad_log',False),'FUSE_TAIL_BASE':('fuse_tail_base',False),'SKIP_TAIL_CLEAR':('skip_tail_clear',False),'COMPACT_TAIL_STORAGE':('compact_tail_storage',False),'TAIL_GRID_WALK':('tail_grid_walk',False),'FLOAT_TAIL_WEIGHTS':('float_tail_weights',False),'FLOAT_TAIL_RESIDUAL':('float_tail_residual',False),'COMPENSATE_RESIDUAL':('compensate_residual',False),'DIRECT_RESIDUAL_WEIGHTS':('direct_residual_weights',False),'GUIDED_GATHER_ROWS':('guided_gather_rows',False),'REUSE_MOMENT_STORAGE':('reuse_moment_storage',False),'HALF_ROW_COEFFICIENTS':('half_row_coefficients',False),'DIRECT_BATCH':('direct_batch',2),'TAIL_X':('tail_x',8),'GUIDED_DIRECT_MOMENTS':('guided_direct_moments',False),'GUIDED_STATIC_WINDOWS':('guided_static_windows',False),'GUIDED_VERTICAL':('guided_vertical',1),'GUIDED_THREADS_Y':('guided_threads_y',self.config.get('tile_y',16)),'GUIDED_BATCH':('guided_batch',1),'GUIDED_SLIDING':('guided_sliding',False),'WAVE_REDUCTION':('wave_reduction',False),'SHARED_PADDING':('shared_padding',0),'HALF_MOMENT_PRODUCTS':('half_moment_products',False),'GATHER_X':('gather_x',8),'GATHER_Y':('gather_y',8),'HALF_GATHER':('half_gather',False),'SCALAR_REDUCTION':('scalar_reduction',False),'LOG_PRODUCT':('log_product',False),'MOMENT_INPUT':('moment_input',False),'PACKED_RESIDUAL':('packed_residual',False),'RESIDUAL_PYRAMID':('residual_pyramid',False),'CURVE_LOG':('curve_log',False),'PRECOMPUTED_EV':('precomputed_ev',False),'SINGLE_WEIGHT':('single_weight',False),'REUSE_SHARED':('reuse_shared',False),'REDUCTION_LOAD':('reduction_load',False),'REDUCTION_GRID':('reduction_grid',4),'GUIDED_RADIUS':('guided_radius',2),'CACHED_BASELINE':('cached_baseline',False),'LOG_EXPOSURE':('log_exposure',False),'TILE_X':('tile_x',16),'TILE_Y':('tile_y',16),'WORK_X':('work_x',8),'WORK_Y':('work_y',8),'SEPARABLE_GUIDED':('separable_guided',False)}
        mapping.update(PYRAMID_X=('pyramid_x',self.config.get('work_x',8)),
                       PYRAMID_Y=('pyramid_y',self.config.get('work_y',8)))
        defines={key:str(int(self.config.get(name,default))) for key,(name,default) in mapping.items()}
        defines['RESIDUAL_SCALE']=str(self.config.get('residual_scale',1.0))
        defines['PACKED_WEIGHT_BIAS']=str(self.config.get('packed_weight_bias',0.0))
        session=device.create_slang_session(compiler_options={'include_paths':[ROOT/'shaders'],'defines':defines})
        self.kernels={name:device.create_compute_kernel(session.load_program('fusion_compact.slang',[name])) for name in ['reconstruct_ev_fused','reduce_setup_gather','guided_moments','reduce_horizontal','reduce_setup_vertical','reduce_setup_cooperative','tail_reconstruct','reconstruct_ev','reduce_setup','downsample_compact','reconstruct_compact','reconstruct_guided']}
        self.unsigned_gather = None
        if self.config.get('gather_unsigned_source'):
            unsigned_session = device.create_slang_session(compiler_options={
                'include_paths': [ROOT/'shaders'],
                'defines': {**defines, 'GATHER_UNSIGNED_SOURCE': '1'}})
            self.unsigned_gather = device.create_compute_kernel(unsigned_session.load_program(
                'fusion_compact.slang', ['reduce_setup_gather']))
        self.final=device.create_compute_kernel(session.load_program(str(Path(__file__).with_name('joint.slang')) if self.config.get('joint_upsample') else 'guided.slang',['apply_joint_linear' if self.config.get('joint_upsample') else 'apply_exposure_production']))
    def render(self,source,ev,bracket=1.2,sigma=.2,*,highlight_ev=None,shadow_ev=None):
        # Keep symmetric callers compatible; asymmetric brackets match the viewer UI.
        highlight_ev = bracket if highlight_ev is None else highlight_ev
        shadow_ev = bracket if shadow_ev is None else shadow_ev
        m=self.mapper;w,h=m.work_source.width,m.work_source.height;levels=m.reconstructed.mip_count
        float_from = self.config.get('residual_float_from', levels)
        if float_from < 1:
            raise ValueError('The mixed residual pyramid must retain at least mip 0 in half')
        if float_from < levels and (not self.config.get('residual_pyramid') or any(
                self.config.get(key) for key in ('residual_float', 'residual_snorm', 'packed_residual', 'packed_snorm'))):
            raise ValueError('Mixed residual storage requires an RG16F residual pyramid')
        compact=m.create_texture(w,h,spy.Format.rg16_float if self.config.get('half_compact') else spy.Format.rg32_float)
        lum=m.create_texture(w,h,spy.Format.rgba16_snorm if self.config.get('packed_snorm') else spy.Format.rgba16_float if self.config.get('packed_residual') else spy.Format.rg16_snorm if self.config.get('residual_snorm') else spy.Format.rg32_float if self.config.get('residual_float') else spy.Format.rg16_float if self.config.get('residual_pyramid') else spy.Format.rgba32_float,levels=min(levels,float_from))
        base_lightness=m.create_texture(w,h,spy.Format.r32_float)
        weights=m.create_texture(w,h,spy.Format.rg16_unorm if self.config.get('residual_pyramid') else spy.Format.r16_unorm if self.config.get('weight_unorm') else spy.Format.r16_float if self.config.get('single_weight') else (spy.Format.rg16_float if self.config.get('half_aux') else spy.Format.rg32_float),levels=levels)
        recon=m.create_texture(w,h,spy.Format.r32_float,levels=levels)
        avg=m.create_texture(w,h,spy.Format.rg16_float if self.config.get('half_aux') else spy.Format.rg32_float)
        moments=m.create_texture(w,h,spy.Format.rgba32_float)
        guide_ev=m.create_texture(w,h,spy.Format.rg16_float if self.config.get('half_guide') else spy.Format.rg32_float)
        final=m.create_texture(source.width,source.height,spy.Format.rgba16_float)
        coarse_float = m.create_texture(max(1,w>>float_from),max(1,h>>float_from),spy.Format.rg32_float,levels=levels-float_from) if float_from < levels else None
        def view(t, mip=0):
            if t is lum and coarse_float is not None and mip >= float_from:
                return coarse_float.create_view(mip=mip-float_from, mip_count=1)
            return t.create_view(mip=mip, mip_count=1)
        enc=self.device.create_command_encoder()
        def dispatch(name,width,height,**bindings):
            if name=='reconstruct_guided' and self.config.get('guided_vertical'):
                width=((width+15)//16)*16
                height=((height+15)//16)*self.config.get('guided_threads_y',16)
            kernel = self.kernels[name]
            if name == 'reduce_setup_gather' and self.unsigned_gather is not None and source.format == spy.Format.r11g11b10_float:
                kernel = self.unsigned_gather
            kernel.dispatch(thread_count=[width,height,1],vars=bindings,command_encoder=enc)
        if self.config.get('separable_reduction'):
            horizontal=m.create_texture(w,h*4,spy.Format.rg32_float)
            dispatch('reduce_horizontal',w,h*4,fullSource=source,horizontalOutput=horizontal,linearSampler=m.sampler)
            dispatch('reduce_setup_vertical',w,h,horizontalSource=horizontal,compactOutput=compact,lightnessOutput=view(lum),weightsOutput=view(weights),baseLightnessOutput=base_lightness,linearSampler=m.sampler,globalEV=ev,highlightEV=highlight_ev,shadowEV=shadow_ev,sigma=sigma,**m.curve.bindings())
        else:
            dispatch('reduce_setup_cooperative' if self.config.get('cooperative_reduction') else ('reduce_setup_gather' if self.config.get('gather_reduction') else 'reduce_setup'),((w+7)//8)*32 if self.config.get('cooperative_reduction') else w,((h+7)//8)*8 if self.config.get('cooperative_reduction') else h,fullSource=source,compactOutput=compact,lightnessOutput=view(lum),weightsOutput=view(weights),linearSampler=m.sampler,reductionRows=4,globalEV=ev,highlightEV=highlight_ev,shadowEV=shadow_ev,sigma=sigma,**m.curve.bindings(),**(dict(baseLightnessOutput=base_lightness) if self.config.get('residual_pyramid') else {}))
        tail_mip=1
        while tail_mip<levels-1 and (max(1,w>>tail_mip)>self.config.get('tail_max_width',32) or max(1,h>>tail_mip)>self.config.get('tail_max_height',16)):tail_mip+=1
        use_tail=self.config.get('tail_fusion') and tail_mip<levels-1
        fuse_fine=self.config.get('fused_fine_reconstruction') and levels>3 and (not use_tail or tail_mip>=3)
        for mip in range(1,tail_mip+1 if use_tail else levels):dispatch('downsample_compact',max(1,w>>mip),max(1,h>>mip),coarseLuminance=view(lum,mip-1),layerWeights=view(weights,mip-1),lightnessOutput=view(lum,mip),weightsOutput=view(weights,mip),linearSampler=m.sampler)
        if use_tail:dispatch('tail_reconstruct',8,8,fineLuminance=view(lum,tail_mip),layerWeights=view(weights,tail_mip),reconstructionOutput=view(recon,tail_mip),tailLevels=levels-tail_mip)
        for mip in reversed(range(tail_mip if use_tail else levels)):
            if fuse_fine and mip in (1,2):continue
            bindings=dict(fineLuminance=view(lum,mip),coarseLuminance=view(lum,min(mip+1,levels-1)),layerWeights=view(weights,mip),previousResult=compact if mip==levels-1 else view(recon,mip+1),linearSampler=m.sampler,isCoarsest=mip==levels-1)
            if mip:dispatch('reconstruct_compact',max(1,w>>mip),max(1,h>>mip),reconstructionOutput=view(recon,mip),**bindings)
            else:
                if fuse_fine:bindings.update(previousResult=view(recon,3),mip1Weights=view(weights,1),mip2Weights=view(weights,2),mip2Luminance=view(lum,2),mip3Luminance=view(lum,3))
                if self.config.get('precomputed_ev'):dispatch('reconstruct_ev_fused' if fuse_fine else 'reconstruct_ev',w,h,compactSource=compact,compactOutput=guide_ev,globalEV=ev,**m.curve.bindings(),**bindings,**(dict(baseLightness=base_lightness) if self.config.get('residual_pyramid') else {}))
                if self.config.get('moment_input'):dispatch('guided_moments',w,h,compactSource=guide_ev,momentOutput=moments,linearSampler=m.sampler)
                if not self.config.get('joint_upsample'):dispatch('reconstruct_guided',w,h,compactSource=guide_ev if self.config.get('precomputed_ev') else compact,averagedOutput=avg,globalEV=ev,**m.curve.bindings(),**bindings,**(dict(momentSource=moments) if self.config.get('moment_input') else {}))
        self.final.dispatch(thread_count=[source.width,source.height,1],vars=dict(fullSource=source,lowExposure=m.low_exposure,averagedCoefficients=avg,colorOutput=final,linearSampler=m.sampler,globalEV=ev,guided=True,**(dict(jointGuideExposure=guide_ev) if self.config.get('joint_upsample') else {})),command_encoder=enc)
        self.device.submit_command_buffer(enc.finish())
        return final.to_numpy(),(guide_ev.to_numpy() if self.config.get('joint_upsample') else avg.to_numpy())

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--variants',nargs='+',default=['half-aux-compute','log-exposure','separable']);ap.add_argument('--out',type=Path,required=True);ap.add_argument('--game-format',action='store_true');ap.add_argument('--width',type=int,default=513);ap.add_argument('--height',type=int,default=289);ap.add_argument('--bracket',type=float,default=1.2);ap.add_argument('--sigma',type=float,default=.2);args=ap.parse_args()
    if min(args.width,args.height)<2 or not np.isfinite([args.bracket,args.sigma]).all() or args.sigma<=0:ap.error('Dimensions must exceed one, bracket must be finite, and sigma must be finite and positive')
    device=spy.Device(enable_hot_reload=False);mapper=ToneMapper(device);candidates={v:Candidate(device,mapper,v) for v in args.variants}
    rng=np.random.default_rng(711);h,w=args.height,args.width;y,x=np.mgrid[:h,:w]
    scenes={
      'log-ramp':np.repeat(np.exp2(-20+36*x[...,None]/(w-1)),3,axis=2),
      'hard-edge':np.repeat(np.where(x[...,None]<w//2,.001,10000.),3,axis=2),
      'colored-edge':np.where((x<w//2)[...,None],np.array([32,.001,.001]),np.array([.001,5000,2.])),
      'fine-checker':np.repeat(np.where(((x//3+y//3)%2)[...,None],16.,.005),3,axis=2),
      'random-hdr':np.minimum(np.exp2(rng.uniform(-30,16,(h,w,3))),65535),
    }
    if args.game_format:
        session=device.create_slang_session()
        pack=device.create_compute_kernel(session.load_program(str(Path(__file__).with_name('pack_source.slang')),['pack_source']))
    records=[];previous={};previous_reference={};temporal=[]
    cases=[(name,rgb,ev) for name,rgb in scenes.items() for ev in [-4,0,4]]
    for frame in range(12):
        # Move a high-contrast edge by fractional pixels, including across tile seams.
        blend=np.clip(x-(w//2+frame*.35)+.5,0,1)[...,None]
        rgb=(1-blend)*np.array([.01,.02,.04])+blend*np.array([100,35,5])
        cases.append((f'motion-{frame:02}',rgb,0))
    for frame in range(16):
        phase=frame/8
        lum=np.exp2(-5+10*x/w+.08*np.sin((x-phase)*np.pi/3)+.04*np.sin(y*np.pi/5))
        rgb=lum[...,None]*np.array([1.,.6,.15])
        cases.append((f'motion-ramp-{frame:02}',rgb,phase*.1))
    for name,rgb,ev in cases:
        if args.game_format:rgb=np.minimum(rgb,[65024.,65024.,64512.])
        rgba=np.concatenate([rgb.astype(np.float32),np.ones((h,w,1),np.float32)],axis=-1);source=create_hdr_texture(device,rgba)
        if args.game_format:
            packed=mapper.create_texture(w,h,spy.Format.r11g11b10_float)
            pack.dispatch(thread_count=[w,h,1],vars=dict(inputTexture=source,outputTexture=packed));source=packed
        enc=device.create_command_encoder();mapper.prepare_weights(enc,source,ev,args.bracket,args.bracket,args.sigma);mapper.prepare_result(enc,source,ev);device.submit_command_buffer(enc.finish());reference=codes(mapper.final_color.to_numpy())
        for variant,candidate in candidates.items():
            linear,avg=candidate.render(source,ev,args.bracket,args.sigma);actual=codes(linear);q=image_quality(reference,actual);q['finite_intermediates']=bool(np.isfinite(avg).all() and np.isfinite(linear).all());records.append(dict(scene=name,ev=ev,variant=variant,quality=q))
            if name.startswith('motion'):
                sequence=name.rsplit('-',1)[0];key=(variant,sequence)
                if key in previous:
                    drift=(actual.astype(float)-previous[key])-(reference.astype(float)-previous_reference[sequence])
                    temporal.append(dict(scene=name,variant=variant,rmse_delta_codes=float(np.sqrt(np.mean(drift**2))),max_delta_codes=float(abs(drift).max())))
                previous[key]=actual.astype(float)
        if name.startswith('motion'):previous_reference[name.rsplit('-',1)[0]]=reference.astype(float)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    accepted=all(r['quality']['accepted'] and r['quality']['finite_intermediates'] for r in records)
    result=dict(accepted=accepted,config=dict(width=w,height=h,game_format=args.game_format,bracket_ev=args.bracket,sigma=args.sigma,variants=args.variants),backend=str(device.info),note='Same desktop backend; synthetic stress and moving-edge differential, not phone temporal capture.',records=records,temporal=temporal)
    args.out.write_text(json.dumps(result,indent=2)+'\n')
    for variant in args.variants:
        selected=[r for r in records if r['variant']==variant];failed=[r for r in selected if not r['quality']['accepted'] or not r['quality']['finite_intermediates']]
        print(variant,'failed',[(r['scene'],r['ev'],round(r['quality']['rmse_codes'],3),r['quality']['max_codes']) for r in failed],flush=True)
        print(variant,'temporal worst',max(t['max_delta_codes'] for t in temporal if t['variant']==variant),flush=True)
    if not accepted:raise SystemExit(1)
if __name__=='__main__':main()
