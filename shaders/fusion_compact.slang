// The mobile residual path can consume the normalized Gaussian pair directly.
// This retains UNORM quantization drift instead of renormalizing it at each level.
#ifndef DIRECT_RESIDUAL_WEIGHTS
#define DIRECT_RESIDUAL_WEIGHTS 0
#endif
#ifndef GUIDED_GATHER_ROWS
#define GUIDED_GATHER_ROWS 0
#endif
#ifndef DIRECT_BATCH
#define DIRECT_BATCH 2
#endif
#ifndef HALF_ROW_COEFFICIENTS
#define HALF_ROW_COEFFICIENTS 0
#endif
#ifndef REUSE_MOMENT_STORAGE
#define REUSE_MOMENT_STORAGE 0
#endif
#ifndef TAIL_X
#define TAIL_X 8
#endif
// Production pass fusion. The default configuration keeps luminance/guide FP32.
// RESIDUAL_PYRAMID stores exposure differences in RG16F, independent weights in
// RG16_UNORM, and the finest middle exposure separately in R32F.
// The legacy graph remains the independent numerical reference.
#include "guided.slang"
#include "zcurve.slang"
#ifndef GUIDED_DIRECT_MOMENTS
#define GUIDED_DIRECT_MOMENTS 0
#endif
#ifndef GUIDED_STATIC_WINDOWS
#define GUIDED_STATIC_WINDOWS 0
#endif
#ifndef GUIDED_VERTICAL
#define GUIDED_VERTICAL 1
#endif
#ifndef GUIDED_THREADS_Y
#define GUIDED_THREADS_Y TILE_Y
#endif
#ifndef GUIDED_BATCH
#define GUIDED_BATCH 1
#endif
#ifndef GUIDED_SLIDING
#define GUIDED_SLIDING 0
#endif
#ifndef WAVE_REDUCTION
#define WAVE_REDUCTION 0
#endif
#ifndef REDUCTION_GRID
#define REDUCTION_GRID 4
#endif
#ifndef CACHED_BASELINE
#define CACHED_BASELINE 0
#endif
#ifndef LOG_EXPOSURE
#define LOG_EXPOSURE 0
#endif
#ifndef GUIDED_RADIUS
#define GUIDED_RADIUS 2
#endif
#ifndef SHARED_PADDING
#define SHARED_PADDING 0
#endif
#ifndef HALF_MOMENT_PRODUCTS
#define HALF_MOMENT_PRODUCTS 0
#endif
#ifndef GATHER_X
#define GATHER_X 8
#endif
#ifndef GATHER_Y
#define GATHER_Y 8
#endif
#ifndef HALF_GATHER
#define HALF_GATHER 0
#endif
#ifndef SCALAR_REDUCTION
#define SCALAR_REDUCTION 0
#endif
#ifndef LOG_PRODUCT
#define LOG_PRODUCT 0
#endif
#ifndef MOMENT_INPUT
#define MOMENT_INPUT 0
#endif
#ifndef RESIDUAL_SCALE
#define RESIDUAL_SCALE 1.0
#endif
#ifndef PACKED_WEIGHT_BIAS
#define PACKED_WEIGHT_BIAS 0.0
#endif
#ifndef PACKED_RESIDUAL
#define PACKED_RESIDUAL 0
#endif
#ifndef RESIDUAL_PYRAMID
#define RESIDUAL_PYRAMID 0
#endif
#ifndef CURVE_LOG
#define CURVE_LOG 0
#endif
#ifndef PRECOMPUTED_EV
#define PRECOMPUTED_EV 0
#endif
#ifndef SINGLE_WEIGHT
#define SINGLE_WEIGHT 0
#endif
#ifndef REDUCTION_LOAD
#define REDUCTION_LOAD 0
#endif
#ifndef WORK_X
#define WORK_X 8
#endif
#ifndef WORK_Y
#define WORK_Y 8
#endif
#ifndef REUSE_SHARED
#define REUSE_SHARED 0
#endif
#ifndef SEPARABLE_GUIDED
#define SEPARABLE_GUIDED 0
#endif
#ifndef TILE_X
#define TILE_X 16
#endif
#ifndef TILE_Y
#define TILE_Y 16
#endif
#if GUIDED_DIRECT_MOMENTS && (!SEPARABLE_GUIDED || !PRECOMPUTED_EV || MOMENT_INPUT || GUIDED_RADIUS != 2)
#error Direct moments require precomputed EV and separable radius-two Guided
#endif
#if GUIDED_GATHER_ROWS && (!GUIDED_DIRECT_MOMENTS || (TILE_Y % 2) != 0)
#error Gather rows require direct radius-two moments and an even output tile height
#endif
#if GUIDED_VERTICAL != 1 && GUIDED_VERTICAL != 2
#error Unsupported vertical Guided batch
#endif
#if GUIDED_VERTICAL == 2 && (!SEPARABLE_GUIDED || MOMENT_INPUT || GUIDED_RADIUS != 2)
#error Vertical reuse requires separable radius-two Guided with local moments
#endif
#if GUIDED_THREADS_Y != TILE_Y && GUIDED_VERTICAL != 2
#error Decoupled Guided threads require vertical output batching
#endif
static const uint inputPitch=TILE_X+4*GUIDED_RADIUS;
static const uint inputHeight=TILE_Y+4*GUIDED_RADIUS;
static const uint coefficientPitch=TILE_X+2*GUIDED_RADIUS;
static const uint coefficientHeight=TILE_Y+2*GUIDED_RADIUS;

RWTexture2D<float2> compactOutput;
Texture2D<float2> compactSource;
RWTexture2D<float> baseLightnessOutput;
Texture2D<float> baseLightness;
RWTexture2D<float4> lightnessOutput;
RWTexture2D<float2> weightsOutput;
float highlightEV;
float shadowEV;
float sigma;

void storeReducedLuma(uint2 pixel,float luminance,float guide)
{
    #if LOG_EXPOSURE
    compactOutput[pixel]=float2(log2(max(luminance,1e-20))+globalEV,guide);
#else
    compactOutput[pixel]=float2(luminance,guide);
#endif
    luminance*=exp2(globalEV);
#if CURVE_LOG
    // Share the input logarithm across all three brackets and avoid log(pow()).
    float3 logInputs=min(log2(max(luminance,1e-38))+float3(-highlightEV,0,shadowEV),log2(zMaxInput));
    float3 numerator=exp2(logInputs*zParameters.x);
    float3 denominator=zParameters.z*exp2(logInputs*(zParameters.x*zParameters.y))+zParameters.w;
    float3 y=luminance>0 ? min(sqrt(numerator/denominator),zMaxLightness) : float3(0);
#else
    float3 y=float3(fusionLightness(luminance*exp2(-highlightEV)),
        fusionLightness(luminance),fusionLightness(luminance*exp2(shadowEV)));
#endif
    float3 distance=y-0.5;
    float3 logWeight=-distance*distance/(2.0*sigma*sigma);
    float3 weights=exp2(logWeight-max(logWeight.x,max(logWeight.y,logWeight.z)));
    weights/=weights.x+weights.y+weights.z;
#if RESIDUAL_PYRAMID
    baseLightnessOutput[pixel]=y.y;
#if PACKED_RESIDUAL
    lightnessOutput[pixel]=float4((y.x-y.y)*RESIDUAL_SCALE,(y.z-y.y)*RESIDUAL_SCALE,weights.x-PACKED_WEIGHT_BIAS,weights.z-PACKED_WEIGHT_BIAS);
#else
    lightnessOutput[pixel]=float4((y.x-y.y)*RESIDUAL_SCALE,(y.z-y.y)*RESIDUAL_SCALE,0,0);
    weightsOutput[pixel]=weights.xz;
#endif
#else
    lightnessOutput[pixel]=float4(y,weights.x);
    weightsOutput[pixel]=weights.yz;
#endif
}

void storeReduced(uint2 pixel,float4 reduced)
{
    storeReducedLuma(pixel,dot(max(reduced.rgb,0.0),float3(0.2126,0.7152,0.0722)),reduced.a);
}

RWTexture2D<float2> horizontalOutput;
Texture2D<float2> horizontalSource;
[shader("compute")]
[numthreads(16,16,1)]
void reduce_horizontal(uint3 tid : SV_DispatchThreadID)
{
    uint w,h;horizontalOutput.GetDimensions(w,h);
    if(tid.x>=w || tid.y>=h)return;
    float2 sum=0;
    for(uint x=0;x<4;x++) {
        float2 uv=float2((float(tid.x)+(float(x)+.5)/4.0)/float(w),(float(tid.y)+.5)/float(h));
        float3 rgb=max(fullSource.SampleLevel(linearSampler,uv,0).rgb,0.0);
        float luminance=dot(rgb,float3(.2126,.7152,.0722));
        sum+=float2(luminance,log2(max(luminance,1e-6)));
    }
    horizontalOutput[tid.xy]=sum*.25;
}
[shader("compute")]
[numthreads(8,8,1)]
void reduce_setup_vertical(uint3 tid : SV_DispatchThreadID)
{
    uint w,h;compactOutput.GetDimensions(w,h);
    if(tid.x>=w || tid.y>=h)return;
    float2 a=horizontalSource.SampleLevel(linearSampler,(float2(tid.xy)+float2(.5,.25))/float2(w,h),0);
    float2 b=horizontalSource.SampleLevel(linearSampler,(float2(tid.xy)+float2(.5,.75))/float2(w,h),0);
    float2 reduced=(a+b)*.5;
    storeReducedLuma(tid.xy,reduced.x,reduced.y);
}

void reduceSampled(uint3 tid)
{
    uint w,h;
    compactOutput.GetDimensions(w,h);
    if(tid.x>=w || tid.y>=h) return;
    float4 sum=0;
#if LOG_PRODUCT
    float mantissaProduct=1.0;
    int exponentSum=0;
#endif
#if REDUCTION_LOAD
    uint sourceWidth,sourceHeight;fullSource.GetDimensions(sourceWidth,sourceHeight);
    bool exactCells=sourceWidth==w*4 && sourceHeight==h*4;
#endif
    for(uint y=0; y<(REDUCTION_GRID == 4 ? reductionRows : REDUCTION_GRID); ++y)
        for(uint x=0; x<REDUCTION_GRID; ++x)
        {
            float2 uv=(float2(tid.xy)+(float2(x,y)+0.5)/float(REDUCTION_GRID))/float2(w,h);
#if REDUCTION_LOAD
            float3 rgb=max(exactCells ? fullSource.Load(int3(tid.xy*4+uint2(x,y),0)).rgb : fullSource.SampleLevel(linearSampler,uv,0).rgb,0.0);
#else
            float3 rgb=max(fullSource.SampleLevel(linearSampler,uv,0).rgb,0.0);
#endif
#if SCALAR_REDUCTION
            float pixelLuminance=dot(rgb,float3(.2126,.7152,.0722));
            sum.x+=pixelLuminance;
#else
            float pixelLuminance=dot(rgb,float3(.2126,.7152,.0722));
#endif
#if LOG_PRODUCT
#if !SCALAR_REDUCTION
            sum.rgb+=rgb;
#endif
            // L is normal and positive after the same 1e-6 guide floor.
            // Sixteen mantissas in [1,2) have a finite product below 65536.
            uint bits=asuint(max(pixelLuminance,1e-6));
            exponentSum+=int((bits>>23)&255)-127;
            mantissaProduct*=asfloat((bits&0x7fffff)|0x3f800000);
#else
#if SCALAR_REDUCTION
            sum.a+=log2(max(pixelLuminance,1e-6));
#else
            sum+=float4(rgb,logGuide(rgb));
#endif
#endif
        }
    float4 reduced=sum/float(REDUCTION_GRID*REDUCTION_GRID);
#if LOG_PRODUCT
    reduced.a=(log2(mantissaProduct)+float(exponentSum))/float(REDUCTION_GRID*REDUCTION_GRID);
#endif
#if SCALAR_REDUCTION
    storeReducedLuma(tid.xy,reduced.x,reduced.a);
#else
    storeReduced(tid.xy,reduced);
#endif
}

[shader("compute")]
[numthreads(WORK_X,WORK_Y,1)]
void reduce_setup(uint3 tid : SV_DispatchThreadID) { reduceSampled(tid); }

[shader("compute")]
[numthreads(GATHER_X,GATHER_Y,1)]
void reduce_setup_gather(uint3 tid : SV_DispatchThreadID)
{
    uint w,h,sw,sh;compactOutput.GetDimensions(w,h);fullSource.GetDimensions(sw,sh);
    if(tid.x>=w || tid.y>=h)return;
    if(sw!=w*4 || sh!=h*4){reduceSampled(tid);return;}
    float sumL=0,sumLog=0;
    for(uint y=0;y<2;y++)for(uint x=0;x<2;x++) {
        float2 uv=(float2(tid.xy)+(float2(x,y)+.5)/2.0)/float2(w,h);
#if HALF_GATHER
        // Opt-in only for finite R11G11B10 input: every channel value is exactly
        // representable in half. Products and luminance sums still use FP32.
        half4 r=half4(max(fullSource.GatherRed(linearSampler,uv),0.0));
        half4 g=half4(max(fullSource.GatherGreen(linearSampler,uv),0.0));
        half4 b=half4(max(fullSource.GatherBlue(linearSampler,uv),0.0));
#else
        float4 r=max(fullSource.GatherRed(linearSampler,uv),0.0);
        float4 g=max(fullSource.GatherGreen(linearSampler,uv),0.0);
        float4 b=max(fullSource.GatherBlue(linearSampler,uv),0.0);
#endif
        float4 luminance=float4(r)*.2126+float4(g)*.7152+float4(b)*.0722;
        sumL+=dot(luminance,float4(1));sumLog+=dot(log2(max(luminance,1e-6)),float4(1));
    }
    storeReducedLuma(tid.xy,sumL/16.0,sumLog/16.0);
}

groupshared float4 reductionPartials[256];
[shader("compute")]
[numthreads(32,8,1)]
void reduce_setup_cooperative(uint3 local : SV_GroupThreadID,uint3 group : SV_GroupID)
{
    uint w,h;compactOutput.GetDimensions(w,h);
    uint2 pixel=group.xy*uint2(8,8)+uint2(local.x/4,local.y);
    uint column=local.x%4,lane=local.y*32+local.x;
#if WAVE_REDUCTION
    // Four consecutive lanes each integrate a 2x2 quad. Validate the mapping
    // instead of assuming a subgroup width or implementation-specific ordering.
    uint waveLane=WaveGetLaneIndex();
    uint first=WaveReadLaneFirst(lane);
    bool ordered=WaveActiveAllTrue(lane==first+waveLane);
    uint sw,sh;fullSource.GetDimensions(sw,sh);
    if(!ordered || (first&3)!=0 || (WaveActiveCountBits(true)&3)!=0 ||
       WaveGetLaneCount()<4 || sw!=w*4 || sh!=h*4) {
        if(column==0) reduceSampled(uint3(pixel,0));
        return;
    }
    float2 uv=(float2(pixel)+(float2(column&1,column>>1)+.5)/2.0)/float2(w,h);
    float4 r=max(fullSource.GatherRed(linearSampler,uv),0.0);
    float4 g=max(fullSource.GatherGreen(linearSampler,uv),0.0);
    float4 b=max(fullSource.GatherBlue(linearSampler,uv),0.0);
    float4 luminance=r*.2126+g*.7152+b*.0722;
    float2 partial=float2(dot(luminance,float4(1)),dot(log2(max(luminance,1e-6)),float4(1)));
    uint cluster=waveLane&~3u;
    float2 total=WaveReadLaneAt(partial,cluster);
    total+=WaveReadLaneAt(partial,cluster+1);
    total+=WaveReadLaneAt(partial,cluster+2);
    total+=WaveReadLaneAt(partial,cluster+3);
    if(column==0 && pixel.x<w && pixel.y<h) storeReducedLuma(pixel,total.x/16.0,total.y/16.0);
#else
    float4 sum=0;
    for(uint y=0;y<4;y++) {
        float2 uv=(float2(pixel)+(float2(column,y)+.5)/4.0)/float2(w,h);
        float3 rgb=max(fullSource.SampleLevel(linearSampler,uv,0).rgb,0.0);
        sum+=float4(rgb,logGuide(rgb));
    }
    reductionPartials[lane]=sum;
    GroupMemoryBarrierWithGroupSync();
    if(column==0 && pixel.x<w && pixel.y<h) {
        sum=((reductionPartials[lane]+reductionPartials[lane+1])+reductionPartials[lane+2])+reductionPartials[lane+3];
        storeReduced(pixel,sum/16.0);
    }
#endif
}

Texture2D<float4> fineLuminance;
Texture2D<float4> coarseLuminance;
Texture2D<float2> layerWeights;
RWTexture2D<float> reconstructionOutput;
Texture2D<float> previousResult;
bool isCoarsest;
RWTexture2D<half> exposureOutput;

float reconstructValue(uint2 pixel, uint w, uint h)
{
    float2 uv=(float2(pixel)+0.5)/float2(w,h);
    float4 fine=fineLuminance[pixel];
#if RESIDUAL_PYRAMID
    float2 detail=fine.xy;
    if(!isCoarsest)detail-=coarseLuminance.SampleLevel(linearSampler,uv,0).xy;
#if PACKED_RESIDUAL
    float2 weights=fine.zw+PACKED_WEIGHT_BIAS;
#else
    float2 weights=layerWeights[pixel];
#endif
    #if !DIRECT_RESIDUAL_WEIGHTS
    weights/=max(weights.x+weights.y+max(1.0-weights.x-weights.y,0.0),1e-20);
#endif
    float2 contribution=detail*weights;
    float value=contribution.x+contribution.y;
#else
    float3 detail=fine.rgb;
    if(!isCoarsest) detail-=coarseLuminance.SampleLevel(linearSampler,uv,0).rgb;
#if SINGLE_WEIGHT
    float middle=layerWeights[pixel].x;
    float3 weights=float3(fine.a,middle,max(1.0-fine.a-middle,0.0));
#else
    float3 weights=float3(fine.a,layerWeights[pixel]);
#endif
    weights/=max(weights.x+weights.y+weights.z,1e-20);
    float3 contribution=detail*weights;
    float value=contribution.x+contribution.y+contribution.z;
#endif
    if(!isCoarsest) value+=previousResult.SampleLevel(linearSampler,uv,0);
    return value;
}

float baselineValue(uint2 pixel)
{
#if RESIDUAL_PYRAMID
    return baseLightness[pixel];
#else
    return fineLuminance[pixel].g;
#endif
}
float reconstructedLightness(uint2 pixel,uint w,uint h)
{
    float value=reconstructValue(pixel,w,h);
#if RESIDUAL_PYRAMID
    value=value/RESIDUAL_SCALE+baseLightness[pixel];
#endif
    return value;
}

half invertExposure(float value, float linearLuminance, float cachedBaseline)
{
    float luminance=linearLuminance*exp2(globalEV);
    float target=clamp(value,0.0,zMaxLightness);
    float baseline=(CACHED_BASELINE != 0) ? cachedBaseline : fusionLightness(luminance);
    half multiplier=half(1.0);
    if(luminance>1e-12 && abs(target-baseline)>2e-6)
    {
        float targetLuminance=inverseFusionLightness(target);
        multiplier=half(clamp(targetLuminance/luminance,exp2(-12.0),exp2(12.0)));
    }
    return multiplier;
}

[shader("compute")]
[numthreads(WORK_X,WORK_Y,1)]
void reconstruct_compact(uint3 tid : SV_DispatchThreadID)
{
    uint w,h;
    reconstructionOutput.GetDimensions(w,h);
    if(tid.x>=w || tid.y>=h) return;
    reconstructionOutput[tid.xy]=reconstructValue(tid.xy,w,h);
}

float compactEV(float value,float2 lg,float baseline)
{
    #if LOG_EXPOSURE
        float lightness=clamp(value,0.0,zMaxLightness);
        float ev=0.0;
        if(lg.x>log2(1e-12) && abs(lightness-baseline)>2e-6)
        {
            float targetLog;
            if(lightness<=0.0) targetLog=-1e20;
            else if(lightness>=zMaxLightness) targetLog=log2(zMaxInput);
            else
            {
                float t=saturate(lightness/zMaxLightness);
                float u=0.5+log2((t+inverseWarpEpsilon)/(1.0-t+inverseWarpEpsilon))/(2.0*inverseWarpSpan);
                float coord=(saturate(u)*float(inverseSize-1)+0.5)/float(inverseSize);
                targetLog=min(inverseLut.SampleLevel(inverseSampler,coord,0),log2(zMaxInput));
            }
            ev=clamp(targetLog-lg.x,-12.0,12.0);
        }
        return float(half(ev));
#else
        half exposure=invertExposure(value,lg.x,baseline);
        return float(half(log2(max(exposure,1e-20))));
#endif
}

[shader("compute")]
[numthreads(WORK_X,WORK_Y,1)]
void reconstruct_ev(uint3 tid : SV_DispatchThreadID)
{
    uint w,h;compactOutput.GetDimensions(w,h);
    if(tid.x>=w || tid.y>=h)return;
    float2 lg=compactSource[tid.xy];
    float ev=compactEV(reconstructedLightness(tid.xy,w,h),lg,baselineValue(tid.xy));
    compactOutput[tid.xy]=float2(ev,lg.y);
}

// Fuse fine reconstruction levels 2 -> 1 -> 0 and exposure recovery.
// The host supplies reconstructed mip 3 and only selects this path when that
// level exists outside the fused tail. Every pyramid level is still included.
// A 16x16 output tile needs a 10x10 mip-1 halo and a 7x7 mip-2 halo. Recompute
// overlapping halos to replace two global writes/reads and dispatch barriers.
// Shared results remain FP32. Software bilinear can differ from texture filtering.
Texture2D<float2> mip1Weights;
Texture2D<float4> mip2Luminance;
Texture2D<float2> mip2Weights;
Texture2D<float4> mip3Luminance;
groupshared float mip2Result[49];
groupshared float mip1Result[100];
[shader("compute")]
[numthreads(16,16,1)]
void reconstruct_ev_fused(uint3 tid : SV_DispatchThreadID, uint3 local : SV_GroupThreadID, uint3 group : SV_GroupID)
{
    uint w,h,pw,ph;compactOutput.GetDimensions(w,h);coarseLuminance.GetDimensions(pw,ph);
    int2 origin=int2(group.xy*16);
    int2 mip1Origin=int2(floor((float2(origin)+.5)*float2(pw,ph)/float2(w,h)-.5));
    uint lane=local.y*16+local.x;
    uint gw,gh;mip2Luminance.GetDimensions(gw,gh);
    int2 mip2Origin=int2(floor((float2(mip1Origin)+.5)*float2(gw,gh)/float2(pw,ph)-.5));
    if(lane<49) {
        int2 p=clamp(mip2Origin+int2(lane%7,lane/7),int2(0),int2(gw-1,gh-1));
        float2 uv=(float2(p)+.5)/float2(gw,gh);
        float2 detail=mip2Luminance[p].xy-mip3Luminance.SampleLevel(linearSampler,uv,0).xy;
        float2 weights=mip2Weights[p];
        #if !DIRECT_RESIDUAL_WEIGHTS
    weights/=max(weights.x+weights.y+max(1.0-weights.x-weights.y,0.0),1e-20);
#endif
        float2 contribution=detail*weights;
        mip2Result[lane]=contribution.x+contribution.y+previousResult.SampleLevel(linearSampler,uv,0);
    }
    GroupMemoryBarrierWithGroupSync();
    if(lane<100) {
        int2 p=clamp(mip1Origin+int2(lane%10,lane/10),int2(0),int2(pw-1,ph-1));
        float2 uv=(float2(p)+.5)/float2(pw,ph);
        float2 detail=coarseLuminance[p].xy-mip2Luminance.SampleLevel(linearSampler,uv,0).xy;
        float2 weights=mip1Weights[p];
        #if !DIRECT_RESIDUAL_WEIGHTS
    weights/=max(weights.x+weights.y+max(1.0-weights.x-weights.y,0.0),1e-20);
#endif
        float2 contribution=detail*weights;
        float2 pos=uv*float2(gw,gh)-.5;
        int2 ip=int2(floor(pos))-mip2Origin;float2 f=frac(pos);uint index=ip.y*7+ip.x;
        float previous=lerp(lerp(mip2Result[index],mip2Result[index+1],f.x),lerp(mip2Result[index+7],mip2Result[index+8],f.x),f.y);
        mip1Result[lane]=contribution.x+contribution.y+previous;
    }
    GroupMemoryBarrierWithGroupSync();
    if(tid.x>=w || tid.y>=h)return;
    float2 uv=(float2(tid.xy)+.5)/float2(w,h);
    float2 pos=uv*float2(pw,ph)-.5;
    int2 ip=int2(floor(pos))-mip1Origin;
    float2 f=frac(pos);
    uint index=ip.y*10+ip.x;
    float previous=lerp(lerp(mip1Result[index],mip1Result[index+1],f.x),lerp(mip1Result[index+10],mip1Result[index+11],f.x),f.y);
    float2 detail=fineLuminance[tid.xy].xy-coarseLuminance.SampleLevel(linearSampler,uv,0).xy;
    float2 weights=layerWeights[tid.xy];
    #if !DIRECT_RESIDUAL_WEIGHTS
    weights/=max(weights.x+weights.y+max(1.0-weights.x-weights.y,0.0),1e-20);
#endif
    float2 contribution=detail*weights;
    float baseline=baseLightness[tid.xy];
    float lightness=(contribution.x+contribution.y+previous)/RESIDUAL_SCALE+baseline;
    float2 lg=compactSource[tid.xy];
    compactOutput[tid.xy]=float2(compactEV(lightness,lg,baseline),lg.y);
}

[shader("compute")]
[numthreads(8,8,1)]
void reconstruct_exposure(uint3 tid : SV_DispatchThreadID)
{
    uint w,h;
    exposureOutput.GetDimensions(w,h);
    if(tid.x>=w || tid.y>=h) return;
    float value=reconstructedLightness(tid.xy,w,h);
    half multiplier=invertExposure(value,compactSource[tid.xy].x,baselineValue(tid.xy));
    exposureOutput[tid.xy]=multiplier;
}

[shader("compute")]
[numthreads(8,8,1)]
void fit_compact(uint3 tid : SV_DispatchThreadID, uint3 localID : SV_GroupThreadID,
                 uint3 groupID : SV_GroupID)
{
    uint w,h;
    coefficientOutput.GetDimensions(w,h);
    uint lane=localID.y*8+localID.x;
    for(uint i=lane; i<144; i+=64)
    {
        int2 p=clamp(int2(groupID.xy*8)+int2(i%12,i/12)-2,int2(0),int2(w-1,h-1));
        fitTile[(i/12)*13+i%12]=float2(compactSource[p].y,float(half(log2(max(lowExposure[p],1e-20)))));
    }
    GroupMemoryBarrierWithGroupSync();
    if(tid.x>=w || tid.y>=h) return;
    coefficientOutput[tid.xy]=solveFit(localID);
}

RWTexture2D<float4> momentOutput;
Texture2D<float4> momentSource;
[shader("compute")]
[numthreads(16,16,1)]
void guided_moments(uint3 tid : SV_DispatchThreadID)
{
    uint w,h;momentOutput.GetDimensions(w,h);
    if(tid.x>=w || tid.y>=h)return;
    float4 sum=0;
    for(int x=-GUIDED_RADIUS;x<=GUIDED_RADIUS;x++) {
        float2 eg=compactSource.SampleLevel(linearSampler,(float2(tid.xy)+float2(x,0)+.5)/float2(w,h),0);
        float g=eg.y,e=eg.x;sum+=float4(g,e,g*g,g*e);
    }
    momentOutput[tid.xy]=sum/float(2*GUIDED_RADIUS+1);
}

// One 16x16 output tile needs 20x20 fitted coefficients and a 24x24 guide/EV halo.
// The default graph recomputes reconstruction/inversion in the tile halo.
// PRECOMPUTED_EV instead loads guide + EV from reconstruct_ev, so expensive
// inverse queries are performed once per low-resolution pixel. Moment sums
// remain FP32 in the retained separable configuration.
groupshared float2 fusedInputs[inputPitch*inputHeight];
#if SEPARABLE_GUIDED && REUSE_SHARED
// Every input read finishes before the row-moment barrier. Coefficients fit
// inside the larger input tile and can reuse its shared-memory allocation.
#define fusedCoefficients fusedInputs
#else
groupshared float2 fusedCoefficients[coefficientPitch*coefficientHeight];
#endif
#if SEPARABLE_GUIDED
static const uint momentPitch=coefficientPitch+SHARED_PADDING;
static const uint rowCoefficientPitch=TILE_X+SHARED_PADDING;
groupshared float4 rowMoments[momentPitch*inputHeight];
#if REUSE_MOMENT_STORAGE && HALF_ROW_COEFFICIENTS
// The coefficient-publication barrier ends every moment read before horizontal
// sums are written. Reuse those dead words without another barrier or rounding.
void storeRowCoefficients(uint index, float2 value)
{
    // Preserve the native half conversion. f32tof16 can round differently on
    // D3D12, so pack the converted values' bits instead of converting again.
    half2 rounded = half2(value);
    uint packed = uint(asuint16(rounded.x)) | (uint(asuint16(rounded.y)) << 16);
    rowMoments[index >> 2][index & 3] = asfloat(packed);
}
float2 loadRowCoefficients(uint index)
{
    uint packed = asuint(rowMoments[index >> 2][index & 3]);
    return float2(f16tof32(packed & 65535), f16tof32(packed >> 16));
}
#else
#if HALF_ROW_COEFFICIENTS
// Round only the horizontal coefficient sums. Moments, variance, fitted
// intercepts and the final vertical accumulation retain FP32 arithmetic.
groupshared half2 rowCoefficients[rowCoefficientPitch*coefficientHeight];
#else
groupshared float2 rowCoefficients[rowCoefficientPitch*coefficientHeight];
#endif
void storeRowCoefficients(uint index, float2 value)
{
#if HALF_ROW_COEFFICIENTS
    rowCoefficients[index]=half2(value);
#else
    rowCoefficients[index]=value;
#endif
}
float2 loadRowCoefficients(uint index) { return float2(rowCoefficients[index]); }
#endif
#endif

[shader("compute")]
[numthreads(TILE_X,GUIDED_THREADS_Y,1)]
void reconstruct_guided(uint3 tid : SV_DispatchThreadID, uint3 localID : SV_GroupThreadID,
                        uint3 groupID : SV_GroupID)
{
    uint w,h;
    averagedOutput.GetDimensions(w,h);
    uint lane=localID.y*TILE_X+localID.x;
    int2 origin=int2(groupID.xy*uint2(TILE_X,TILE_Y));
#if !MOMENT_INPUT && !GUIDED_DIRECT_MOMENTS
    for(uint i=lane; i<inputPitch*inputHeight; i+=TILE_X*GUIDED_THREADS_Y)
    {
        int2 p=clamp(origin+int2(i%inputPitch,i/inputPitch)-2*GUIDED_RADIUS,int2(0),int2(w-1,h-1));
        float2 lg=compactSource[p];
#if PRECOMPUTED_EV
        fusedInputs[i]=lg.yx;
#else
        fusedInputs[i]=float2(lg.y,compactEV(reconstructedLightness(uint2(p),w,h),lg,baselineValue(uint2(p))));
#endif
    }
    GroupMemoryBarrierWithGroupSync();
#if SEPARABLE_GUIDED
    // FP32 moments around one tile anchor avoid large absolute-log products.
    // Keep the original 5x5 support; only the arithmetic grouping changes.
    float anchor=fusedInputs[(2*GUIDED_RADIUS)*inputPitch+2*GUIDED_RADIUS].x;
#if GUIDED_BATCH > 1
    // Each lane owns a short run of adjacent windows. Cache their overlapping
    // inputs in registers; preserve the tile anchor and FP32 moment products.
    static const uint chunks=(coefficientPitch+GUIDED_BATCH-1)/GUIDED_BATCH;
    for(uint chunk=lane;chunk<chunks*inputHeight;chunk+=TILE_X*GUIDED_THREADS_Y) {
        uint row=chunk/chunks,col=(chunk%chunks)*GUIDED_BATCH;
        float4 values[GUIDED_BATCH+2*GUIDED_RADIUS];
        [unroll] for(uint x=0;x<GUIDED_BATCH+2*GUIDED_RADIUS;x++) {
            float2 v=fusedInputs[row*inputPitch+min(col+x,inputPitch-1)];
            float g=v.x-anchor,e=v.y;
            values[x]=float4(g,e,g*g,g*e);
        }
        float4 sum=0;
        [unroll] for(uint j=0;j<GUIDED_BATCH;j++) {
#if GUIDED_SLIDING
            if(j==0) {
                [unroll] for(uint x=0;x<=2*GUIDED_RADIUS;x++)sum+=values[x];
            } else {
                sum-=values[j-1];sum+=values[j+2*GUIDED_RADIUS];
            }
#else
            sum=0;
            [unroll] for(uint x=0;x<=2*GUIDED_RADIUS;x++)sum+=values[j+x];
#endif
            if(col+j<coefficientPitch)rowMoments[row*momentPitch+col+j]=sum;
        }
    }
#else
    for(uint i=lane;i<coefficientPitch*inputHeight;i+=TILE_X*GUIDED_THREADS_Y)
    {
        uint row=i/coefficientPitch, col=i%coefficientPitch;
        float4 moments=0;
        for(uint x=0;x<=2*GUIDED_RADIUS;x++) {
            float2 sample=fusedInputs[row*inputPitch+col+x];
#if HALF_MOMENT_PRODUCTS
            half g=half(sample.x-anchor),e=half(sample.y);
            moments+=float4(float(g),float(e),float(g*g),float(g*e));
#else
            float g=sample.x-anchor,e=sample.y;
            moments+=float4(g,e,g*g,g*e);
#endif
        }
#if SHARED_PADDING
        rowMoments[row*momentPitch+col]=moments;
#else
        rowMoments[i]=moments;
#endif
    }
#endif
    GroupMemoryBarrierWithGroupSync();
#endif
#endif
#if GUIDED_DIRECT_MOMENTS
    // Read-only input permits redundant cached loads instead of a shared tile
    // publication barrier. Keep the same tile anchor and FP32 moment order.
    float anchor=compactSource[clamp(origin,int2(0),int2(w-1,h-1))].y;
#if GUIDED_GATHER_ROWS
    // A Gather covers two adjacent rows. Integrate columns 0..3 with four
    // component gathers, then load column 4 directly. Keep the same anchor,
    // five-point support and FP32 accumulation before the existing barrier.
    for(uint task=lane;task<coefficientPitch*(inputHeight/2);task+=TILE_X*GUIDED_THREADS_Y) {
        uint col=task%coefficientPitch,row=(task/coefficientPitch)*2;
        float4 first=0,second=0;
        [unroll] for(uint pair=0;pair<2;pair++) {
            float2 uv=(float2(origin)+float2(col+pair*2,row)-float(2*GUIDED_RADIUS)+1.)/float2(w,h);
            float4 e=compactSource.GatherRed(linearSampler,uv);
            float4 g=compactSource.GatherGreen(linearSampler,uv)-anchor;
            first+=float4(g.w,e.w,g.w*g.w,g.w*e.w);
            second+=float4(g.x,e.x,g.x*g.x,g.x*e.x);
            if(pair<2) {
                first+=float4(g.z,e.z,g.z*g.z,g.z*e.z);
                second+=float4(g.y,e.y,g.y*g.y,g.y*e.y);
            }
        }
        int2 last=origin+int2(col+4,row)-2*GUIDED_RADIUS;
        float2 last0=compactSource[clamp(last,int2(0),int2(w-1,h-1))];
        float2 last1=compactSource[clamp(last+int2(0,1),int2(0),int2(w-1,h-1))];
        float g0=last0.y-anchor,g1=last1.y-anchor;
        first+=float4(g0,last0.x,g0*g0,g0*last0.x);
        second+=float4(g1,last1.x,g1*g1,g1*last1.x);
        rowMoments[row*momentPitch+col]=first;
        rowMoments[(row+1)*momentPitch+col]=second;
    }
#else
    static const uint directChunks=(coefficientPitch+DIRECT_BATCH-1)/DIRECT_BATCH;
    for(uint task=lane;task<directChunks*inputHeight;task+=TILE_X*GUIDED_THREADS_Y) {
        uint row=task/directChunks,col=(task%directChunks)*DIRECT_BATCH;
        float4 values[DIRECT_BATCH+4];
        [unroll] for(uint k=0;k<DIRECT_BATCH+4;k++) {
            int2 p=clamp(origin+int2(col+k,row)-2*GUIDED_RADIUS,int2(0),int2(w-1,h-1));
            float2 lg=compactSource[p];
            float g=lg.y-anchor,e=lg.x;
            values[k]=float4(g,e,g*g,g*e);
        }
        [unroll] for(uint j=0;j<DIRECT_BATCH;j++) if(col+j<coefficientPitch) {
            float4 moments=0;
            [unroll] for(uint k=0;k<5;k++)moments+=values[j+k];
            rowMoments[row*momentPitch+col+j]=moments;
        }
    }
#endif
    GroupMemoryBarrierWithGroupSync();
#endif
#if GUIDED_VERTICAL == 2
    // Two adjacent vertical windows share six rows. Preserve summation order.
    for(uint task=lane;task<coefficientPitch*((coefficientHeight+1)/2);task+=TILE_X*GUIDED_THREADS_Y) {
        uint col=task%coefficientPitch,row=(task/coefficientPitch)*2;
        int2 first=clamp(origin+int2(col,row)-GUIDED_RADIUS,int2(0),int2(w-1,h-1));
        int2 start=first-origin+GUIDED_RADIUS;
        float4 cached[6];
        [unroll] for(uint k=0;k<6;k++) cached[k]=rowMoments[min(start.y+int(k),int(inputHeight-1))*momentPitch+start.x];
        [unroll] for(uint j=0;j<2;j++) if(row+j<coefficientHeight) {
            int cy=clamp(origin.y+int(row+j)-GUIDED_RADIUS,0,int(h-1));
            uint offset=uint(cy-first.y);
            float4 moments=0;
#if GUIDED_STATIC_WINDOWS
            // Avoid dynamic indexing of a private register array at clamped edges.
            if(offset==0) {
                [unroll] for(uint k=0;k<5;k++) moments+=cached[k];
            } else {
                [unroll] for(uint k=0;k<5;k++) moments+=cached[k+1];
            }
#else
            [unroll] for(uint k=0;k<5;k++) moments+=cached[offset+k];
#endif
            moments/=25.0;
            float variance=max(moments.z-moments.x*moments.x,0.0);
            half covariance=half(moments.w-moments.x*moments.y);
            half denominator=half(variance+0.04);
            half aa=covariance/denominator;
            fusedCoefficients[(row+j)*coefficientPitch+col]=float2(float(aa),moments.y-float(aa)*(moments.x+anchor));
        }
    }
#else
    for(uint i=lane; i<coefficientPitch*coefficientHeight; i+=TILE_X*GUIDED_THREADS_Y)
    {
        int2 p=clamp(origin+int2(i%coefficientPitch,i/coefficientPitch)-GUIDED_RADIUS,int2(0),int2(w-1,h-1));
        int2 centerIndex=p-origin+2*GUIDED_RADIUS;
#if MOMENT_INPUT
        float2 uv=(float2(p)+.5)/float2(w,h),texel=1.0/float2(w,h);
        // Radius two: three bilinear reads exactly cover the five source rows.
        float4 moments=momentSource.SampleLevel(linearSampler,uv+texel*float2(0,-1.5),0)*2.0;
        moments+=momentSource.SampleLevel(linearSampler,uv+texel*float2(0,.5),0)*2.0;
        moments+=momentSource.SampleLevel(linearSampler,uv+texel*float2(0,2),0);
        moments*=.2;
        float center=0;
        float meanG=moments.x,meanE=moments.y,meanGG=moments.z,meanGE=moments.w;
#elif SEPARABLE_GUIDED
        float4 moments=0;
        for(int y=-GUIDED_RADIUS;y<=GUIDED_RADIUS;y++)
            moments+=rowMoments[(centerIndex.y+y)*momentPitch+centerIndex.x-GUIDED_RADIUS];
        moments/=float((2*GUIDED_RADIUS+1)*(2*GUIDED_RADIUS+1));
        float center=anchor;
        float meanG=moments.x,meanE=moments.y,meanGG=moments.z,meanGE=moments.w;
#else
        float center=fusedInputs[centerIndex.y*inputPitch+centerIndex.x].x;
        float meanG=0,meanE=0,meanGG=0,meanGE=0;
        for(int y=-GUIDED_RADIUS; y<=GUIDED_RADIUS; ++y)
            for(int x=-GUIDED_RADIUS; x<=GUIDED_RADIUS; ++x)
            {
                float2 cached=fusedInputs[(centerIndex.y+y)*inputPitch+centerIndex.x+x];
                half g=half(cached.x-center);
                half e=half(cached.y);
                meanG+=g; meanE+=e; meanGG+=float(g*g); meanGE+=float(g*e);
            }
        meanG/=float((2*GUIDED_RADIUS+1)*(2*GUIDED_RADIUS+1)); meanE/=float((2*GUIDED_RADIUS+1)*(2*GUIDED_RADIUS+1)); meanGG/=float((2*GUIDED_RADIUS+1)*(2*GUIDED_RADIUS+1)); meanGE/=float((2*GUIDED_RADIUS+1)*(2*GUIDED_RADIUS+1));
#endif
        float variance=max(meanGG-meanG*meanG,0.0);
        half covariance=half(meanGE-meanG*meanE);
        half denominator=half(variance+0.04);
        half a=covariance/denominator;
        fusedCoefficients[i]=float2(float(a),meanE-float(a)*(meanG+center));
    }
#endif
    GroupMemoryBarrierWithGroupSync();
#if SEPARABLE_GUIDED
#if GUIDED_BATCH > 1
    static const uint coefficientChunks=(TILE_X+GUIDED_BATCH-1)/GUIDED_BATCH;
    for(uint chunk=lane;chunk<coefficientChunks*coefficientHeight;chunk+=TILE_X*GUIDED_THREADS_Y) {
        uint row=chunk/coefficientChunks,col=(chunk%coefficientChunks)*GUIDED_BATCH;
        float2 values[GUIDED_BATCH+2*GUIDED_RADIUS];
        [unroll] for(uint x=0;x<GUIDED_BATCH+2*GUIDED_RADIUS;x++)
            values[x]=fusedCoefficients[row*coefficientPitch+min(col+x,coefficientPitch-1)];
        float2 sum=0;
        [unroll] for(uint j=0;j<GUIDED_BATCH;j++) {
#if GUIDED_SLIDING
            if(j==0) {
                [unroll] for(uint x=0;x<=2*GUIDED_RADIUS;x++)sum+=values[x];
            } else {
                sum-=values[j-1];sum+=values[j+2*GUIDED_RADIUS];
            }
#else
            sum=0;
            [unroll] for(uint x=0;x<=2*GUIDED_RADIUS;x++)sum+=values[j+x];
#endif
            if(col+j<TILE_X)storeRowCoefficients(row*rowCoefficientPitch+col+j,sum);
        }
    }
#else
    for(uint i=lane;i<TILE_X*coefficientHeight;i+=TILE_X*GUIDED_THREADS_Y) {
        uint row=i/TILE_X,col=i%TILE_X;
        float2 sum=0;
        for(uint x=0;x<=2*GUIDED_RADIUS;x++)sum+=fusedCoefficients[row*coefficientPitch+col+x];
#if SHARED_PADDING
        storeRowCoefficients(row*rowCoefficientPitch+col,sum);
#else
        storeRowCoefficients(i,sum);
#endif
    }
#endif
    GroupMemoryBarrierWithGroupSync();
#if GUIDED_VERTICAL == 2
    for(uint task=lane;task<TILE_X*((TILE_Y+1)/2);task+=TILE_X*GUIDED_THREADS_Y) {
        uint col=task%TILE_X,row=(task/TILE_X)*2;
        float2 cached[6];
        [unroll] for(uint k=0;k<6;k++) cached[k]=loadRowCoefficients(min(row+k,coefficientHeight-1)*rowCoefficientPitch+col);
        [unroll] for(uint j=0;j<2;j++) {
            uint2 pixel=uint2(origin)+uint2(col,row+j);
            if(row+j<TILE_Y && pixel.x<w && pixel.y<h) {
                float2 sum=0;
                [unroll] for(uint k=0;k<5;k++)sum+=cached[j+k];
                averagedOutput[pixel]=sum/25.0;
            }
        }
    }
    return;
#else
    if(tid.x>=w || tid.y>=h) return;
    float2 sum=0;
    for(uint y=0;y<=2*GUIDED_RADIUS;y++)sum+=loadRowCoefficients((localID.y+y)*rowCoefficientPitch+localID.x);
#endif
#else
    if(tid.x>=w || tid.y>=h) return;
    float2 sum=0;
    for(int y=-GUIDED_RADIUS; y<=GUIDED_RADIUS; ++y)
        for(int x=-GUIDED_RADIUS; x<=GUIDED_RADIUS; ++x)
            sum+=fusedCoefficients[(localID.y+y+GUIDED_RADIUS)*coefficientPitch+localID.x+x+GUIDED_RADIUS];
#endif
#if GUIDED_VERTICAL != 2
    averagedOutput[tid.xy]=sum/float((2*GUIDED_RADIUS+1)*(2*GUIDED_RADIUS+1));
#endif
}

// Both packed pyramids use the same four bilinear coordinates and arithmetic.
[shader("compute")]
[numthreads(WORK_X,WORK_Y,1)]
void downsample_compact(uint3 tid : SV_DispatchThreadID)
{
    uint w,h,iw,ih;
    lightnessOutput.GetDimensions(w,h);
    coarseLuminance.GetDimensions(iw,ih);
    if(tid.x>=w || tid.y>=h) return;
    float2 uv=(float2(tid.xy)+0.5)/float2(w,h);
    float2 texel=1.0/float2(iw,ih);
    float4 a=coarseLuminance.SampleLevel(linearSampler,uv+texel*float2(-1,-1),0);
    a+=coarseLuminance.SampleLevel(linearSampler,uv+texel*float2(1,-1),0);
    a+=coarseLuminance.SampleLevel(linearSampler,uv+texel*float2(-1,1),0);
    a+=coarseLuminance.SampleLevel(linearSampler,uv+texel*float2(1,1),0);
#if !PACKED_RESIDUAL
    float2 b=layerWeights.SampleLevel(linearSampler,uv+texel*float2(-1,-1),0);
    b+=layerWeights.SampleLevel(linearSampler,uv+texel*float2(1,-1),0);
    b+=layerWeights.SampleLevel(linearSampler,uv+texel*float2(-1,1),0);
    b+=layerWeights.SampleLevel(linearSampler,uv+texel*float2(1,1),0);
    weightsOutput[tid.xy]=b*0.25;
#endif
    lightnessOutput[tid.xy]=a*0.25;
}

// Optional small pyramid tail in one workgroup. The base is at most 32x16;
// all mip pixels together fit 683 entries. This is an approximate candidate:
// shared-memory bilinear interpolation replaces hardware texture interpolation.
groupshared float4 tailLightness[683];
groupshared float2 tailWeights[683];
groupshared float tailResult[683];
uint tailLevels;
struct TailSample { float4 lightness; float2 weights; float reconstruction; };
TailSample sampleTail(uint offset,uint2 size,float2 uv)
{
    float2 pos=uv*float2(size)-0.5;
    int2 base=int2(floor(pos));float2 f=pos-float2(base);
    int2 p0=clamp(base,int2(0),int2(size)-1),p1=clamp(base+1,int2(0),int2(size)-1);
    uint a=offset+p0.y*size.x+p0.x,b=offset+p0.y*size.x+p1.x;
    uint c=offset+p1.y*size.x+p0.x,d=offset+p1.y*size.x+p1.x;
    TailSample value;
    value.lightness=lerp(lerp(tailLightness[a],tailLightness[b],f.x),lerp(tailLightness[c],tailLightness[d],f.x),f.y);
    value.weights=lerp(lerp(tailWeights[a],tailWeights[b],f.x),lerp(tailWeights[c],tailWeights[d],f.x),f.y);
    value.reconstruction=lerp(lerp(tailResult[a],tailResult[b],f.x),lerp(tailResult[c],tailResult[d],f.x),f.y);
    return value;
}
[shader("compute")]
[numthreads(TAIL_X,8,1)]
void tail_reconstruct(uint3 local : SV_GroupThreadID)
{
    uint w,h;reconstructionOutput.GetDimensions(w,h);
    uint lane=local.y*TAIL_X+local.x;
    uint levelOffset=0;uint2 currentSize=uint2(w,h);
    for(uint i=lane;i<w*h;i+=TAIL_X*8){uint2 p=uint2(i%w,i/w);tailLightness[i]=fineLuminance[p];tailWeights[i]=layerWeights[p];tailResult[i]=0;}
    GroupMemoryBarrierWithGroupSync();
    for(uint m=1;m<tailLevels;m++) {
        uint2 previous=currentSize;uint previousOffset=levelOffset;
        currentSize=max(previous/2,uint2(1));levelOffset+=previous.x*previous.y;
        uint2 size=currentSize;uint outputOffset=levelOffset;
        for(uint i=lane;i<size.x*size.y;i+=TAIL_X*8) {
            float2 uv=(float2(i%size.x,i/size.x)+.5)/float2(size),texel=1.0/float2(previous);
            TailSample a=sampleTail(previousOffset,previous,uv+texel*float2(-1,-1));
            TailSample b=sampleTail(previousOffset,previous,uv+texel*float2(1,-1));
            TailSample c=sampleTail(previousOffset,previous,uv+texel*float2(-1,1));
            TailSample d=sampleTail(previousOffset,previous,uv+texel*float2(1,1));
            uint index=outputOffset+i;
#if RESIDUAL_PYRAMID
            // Preserve the retained pyramid's per-level RG16F / RG16_UNORM storage.
            float2 residual=(((a.lightness.xy+b.lightness.xy)+c.lightness.xy)+d.lightness.xy)*.25;
            tailLightness[index]=float4(float2(half2(residual)),0,0);
            float2 weights=(((a.weights+b.weights)+c.weights)+d.weights)*.25;
            tailWeights[index]=floor(saturate(weights)*65535.0+0.5)/65535.0;
#else
            tailLightness[index]=((a.lightness+b.lightness)+c.lightness+d.lightness)*.25;
            tailWeights[index]=float2(half2(((a.weights+b.weights)+c.weights+d.weights)*.25));
#endif
            tailResult[index]=0;
        }
        GroupMemoryBarrierWithGroupSync();
    }
    for(int m=int(tailLevels)-1;m>=0;m--) {
        uint2 size=max(uint2(w,h)>>m,uint2(1));uint outputOffset=levelOffset;
        uint2 coarseSize=max(size/2,uint2(1));uint coarseOffset=levelOffset+size.x*size.y;
        bool coarsest=m==int(tailLevels)-1;
        for(uint i=lane;i<size.x*size.y;i+=TAIL_X*8) {
            uint index=outputOffset+i;float4 fine=tailLightness[index];float3 detail=fine.rgb;float previous=0;
            if(!coarsest){TailSample coarse=sampleTail(coarseOffset,coarseSize,(float2(i%size.x,i/size.x)+.5)/float2(size));detail-=coarse.lightness.rgb;previous=coarse.reconstruction;}
#if RESIDUAL_PYRAMID
            float2 weights=tailWeights[index];
            #if !DIRECT_RESIDUAL_WEIGHTS
    weights/=max(weights.x+weights.y+max(1.0-weights.x-weights.y,0.0),1e-20);
#endif
            float2 contribution=detail.xy*weights;
            float value=(contribution.x+contribution.y)+previous;
#else
            float3 weights=float3(fine.a,tailWeights[index]);weights/=max(weights.x+weights.y+weights.z,1e-20);
            float3 contribution=detail*weights;float value=(contribution.x+contribution.y+contribution.z)+previous;
#endif
            if(m==0)reconstructionOutput[uint2(i%w,i/w)]=value;
            else tailResult[index]=value;
        }
        if(m>0)GroupMemoryBarrierWithGroupSync();
        if(m>0){uint2 finer=max(uint2(w,h)>>(m-1),uint2(1));levelOffset-=finer.x*finer.y;}
    }
}
