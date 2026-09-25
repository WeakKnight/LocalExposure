// Weighted residual reconstruction and inverse-curve exposure recovery.
// Pyramid textures pack residuals in xy and weights - 0.5 in zw.
// Input guide/log luminance and baseline; output recovered EV / guide.
Texture2D<float2> compactSource;
Texture2D<float> baseLightness;
RWTexture2D<float2> compactOutput;
SamplerState linearSampler;
// Inverse curve stores log luminance at logit-spaced lightness coordinates.
Texture1D<float> inverseLut;
SamplerState inverseSampler;
uint inverseSize;
float inverseWarpEpsilon;
float inverseWarpSpan;
float zMaxInput;
float zMaxLightness;

Texture2D<float4> fineLuminance;
Texture2D<float4> coarseLuminance;
RWTexture2D<float> reconstructionOutput;
Texture2D<float> previousResult;
bool isCoarsest;

// Additional mip inputs and tile storage for reconstruct_ev_fused.
Texture2D<float4> mip2Luminance;
Texture2D<float4> mip3Luminance;
groupshared float mip2Result[49];
groupshared float mip1Result[100];

float reconstructValue(uint2 pixel, uint w, uint h)
{
    float2 uv=(float2(pixel)+0.5)/float2(w,h);
    float4 fine=fineLuminance[pixel];
    float2 detail=fine.xy;
    if(!isCoarsest)detail-=coarseLuminance.SampleLevel(linearSampler,uv,0).xy;
    float2 weights=fine.zw+.5;
    float2 contribution=detail*weights;
    float value=contribution.x+contribution.y;
    if(!isCoarsest) value+=previousResult.SampleLevel(linearSampler,uv,0);
    return value;
}

float baselineValue(uint2 pixel)
{
    return baseLightness[pixel];
}
float reconstructedLightness(uint2 pixel,uint w,uint h)
{
    float value=reconstructValue(pixel,w,h);
    value=value+baseLightness[pixel];
    return value;
}

[shader("compute")]
[numthreads(8,8,1)]
void reconstruct_compact(uint3 tid : SV_DispatchThreadID)
{
    uint w,h;
    reconstructionOutput.GetDimensions(w,h);
    if(tid.x>=w || tid.y>=h) return;
    reconstructionOutput[tid.xy]=reconstructValue(tid.xy,w,h);
}

float compactEV(float value,float2 lg,float baseline)
{
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
}

[shader("compute")]
[numthreads(8,8,1)]
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
        float2 weights=mip2Luminance[p].zw+.5;
        float2 contribution=detail*weights;
        mip2Result[lane]=contribution.x+contribution.y+previousResult.SampleLevel(linearSampler,uv,0);
    }
    GroupMemoryBarrierWithGroupSync();
    if(lane<100) {
        int2 p=clamp(mip1Origin+int2(lane%10,lane/10),int2(0),int2(pw-1,ph-1));
        float2 uv=(float2(p)+.5)/float2(pw,ph);
        float2 detail=coarseLuminance[p].xy-mip2Luminance.SampleLevel(linearSampler,uv,0).xy;
        float2 weights=coarseLuminance[p].zw+.5;
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
    float2 weights=fineLuminance[tid.xy].zw+.5;
    float2 contribution=detail*weights;
    float baseline=baseLightness[tid.xy];
    float lightness=(contribution.x+contribution.y+previous)+baseline;
    float2 lg=compactSource[tid.xy];
    compactOutput[tid.xy]=float2(compactEV(lightness,lg,baseline),lg.y);
}


