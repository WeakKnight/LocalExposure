// Production pass fusion. The default configuration keeps luminance/guide FP32.
// RESIDUAL_PYRAMID stores exposure differences in RG16F, independent weights in
// RG16_UNORM, and the finest middle exposure separately in R32F.
// The legacy graph remains the independent numerical reference.
#include "guided.slang"
#include "zcurve.slang"
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
    weights/=max(weights.x+weights.y+max(1.0-weights.x-weights.y,0.0),1e-20);
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
groupshared float2 rowCoefficients[rowCoefficientPitch*coefficientHeight];
#endif

[shader("compute")]
[numthreads(TILE_X,TILE_Y,1)]
void reconstruct_guided(uint3 tid : SV_DispatchThreadID, uint3 localID : SV_GroupThreadID,
                        uint3 groupID : SV_GroupID)
{
    uint w,h;
    averagedOutput.GetDimensions(w,h);
    uint lane=localID.y*TILE_X+localID.x;
    int2 origin=int2(groupID.xy*uint2(TILE_X,TILE_Y));
#if !MOMENT_INPUT
    for(uint i=lane; i<inputPitch*inputHeight; i+=TILE_X*TILE_Y)
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
    for(uint chunk=lane;chunk<chunks*inputHeight;chunk+=TILE_X*TILE_Y) {
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
    for(uint i=lane;i<coefficientPitch*inputHeight;i+=TILE_X*TILE_Y)
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
    for(uint i=lane; i<coefficientPitch*coefficientHeight; i+=TILE_X*TILE_Y)
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
    GroupMemoryBarrierWithGroupSync();
#if SEPARABLE_GUIDED
#if GUIDED_BATCH > 1
    static const uint coefficientChunks=(TILE_X+GUIDED_BATCH-1)/GUIDED_BATCH;
    for(uint chunk=lane;chunk<coefficientChunks*coefficientHeight;chunk+=TILE_X*TILE_Y) {
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
            if(col+j<TILE_X)rowCoefficients[row*rowCoefficientPitch+col+j]=sum;
        }
    }
#else
    for(uint i=lane;i<TILE_X*coefficientHeight;i+=TILE_X*TILE_Y) {
        uint row=i/TILE_X,col=i%TILE_X;
        float2 sum=0;
        for(uint x=0;x<=2*GUIDED_RADIUS;x++)sum+=fusedCoefficients[row*coefficientPitch+col+x];
#if SHARED_PADDING
        rowCoefficients[row*rowCoefficientPitch+col]=sum;
#else
        rowCoefficients[i]=sum;
#endif
    }
#endif
    GroupMemoryBarrierWithGroupSync();
    if(tid.x>=w || tid.y>=h) return;
    float2 sum=0;
    for(uint y=0;y<=2*GUIDED_RADIUS;y++)sum+=rowCoefficients[(localID.y+y)*rowCoefficientPitch+localID.x];
#else
    if(tid.x>=w || tid.y>=h) return;
    float2 sum=0;
    for(int y=-GUIDED_RADIUS; y<=GUIDED_RADIUS; ++y)
        for(int x=-GUIDED_RADIUS; x<=GUIDED_RADIUS; ++x)
            sum+=fusedCoefficients[(localID.y+y+GUIDED_RADIUS)*coefficientPitch+localID.x+x+GUIDED_RADIUS];
#endif
    averagedOutput[tid.xy]=sum/float((2*GUIDED_RADIUS+1)*(2*GUIDED_RADIUS+1));
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
[numthreads(8,8,1)]
void tail_reconstruct(uint3 local : SV_GroupThreadID)
{
    uint w,h;reconstructionOutput.GetDimensions(w,h);
    uint lane=local.y*8+local.x;
    uint offsets[6];uint2 sizes[6];offsets[0]=0;sizes[0]=uint2(w,h);
    for(uint m=1;m<tailLevels;m++){offsets[m]=offsets[m-1]+sizes[m-1].x*sizes[m-1].y;sizes[m]=max(sizes[m-1]/2,uint2(1));}
    for(uint i=lane;i<w*h;i+=64){uint2 p=uint2(i%w,i/w);tailLightness[i]=fineLuminance[p];tailWeights[i]=layerWeights[p];tailResult[i]=0;}
    GroupMemoryBarrierWithGroupSync();
    for(uint m=1;m<tailLevels;m++) {
        uint2 size=sizes[m],previous=sizes[m-1];
        for(uint i=lane;i<size.x*size.y;i+=64) {
            float2 uv=(float2(i%size.x,i/size.x)+.5)/float2(size),texel=1.0/float2(previous);
            TailSample a=sampleTail(offsets[m-1],previous,uv+texel*float2(-1,-1));
            TailSample b=sampleTail(offsets[m-1],previous,uv+texel*float2(1,-1));
            TailSample c=sampleTail(offsets[m-1],previous,uv+texel*float2(-1,1));
            TailSample d=sampleTail(offsets[m-1],previous,uv+texel*float2(1,1));
            uint index=offsets[m]+i;
            tailLightness[index]=((a.lightness+b.lightness)+c.lightness+d.lightness)*.25;
            tailWeights[index]=float2(half2(((a.weights+b.weights)+c.weights+d.weights)*.25));
            tailResult[index]=0;
        }
        GroupMemoryBarrierWithGroupSync();
    }
    for(int m=int(tailLevels)-1;m>=0;m--) {
        uint2 size=sizes[m];bool coarsest=m==int(tailLevels)-1;
        for(uint i=lane;i<size.x*size.y;i+=64) {
            uint index=offsets[m]+i;float4 fine=tailLightness[index];float3 detail=fine.rgb;float previous=0;
            if(!coarsest){TailSample coarse=sampleTail(offsets[m+1],sizes[m+1],(float2(i%size.x,i/size.x)+.5)/float2(size));detail-=coarse.lightness.rgb;previous=coarse.reconstruction;}
            float3 weights=float3(fine.a,tailWeights[index]);weights/=max(weights.x+weights.y+weights.z,1e-20);
            float3 contribution=detail*weights;tailResult[index]=(contribution.x+contribution.y+contribution.z)+previous;
        }
        GroupMemoryBarrierWithGroupSync();
    }
    for(uint i=lane;i<w*h;i+=64)reconstructionOutput[uint2(i%w,i/w)]=tailResult[i];
}
