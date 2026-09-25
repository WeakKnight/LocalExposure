// HDR reduction, three-exposure lightness and Gaussian weights.
// Inputs: full-resolution HDR, exposure brackets and fitted curve parameters.
Texture2D<float4> fullSource;
SamplerState linearSampler;
float globalEV;
float highlightEV;
float shadowEV;
float sigma;
float4 zParameters;
float zMaxInput;
float zMaxLightness;
// Runtime bound (always 4) keeps reduction register pressure down on Mali.
uint reductionRows;
// Outputs: log luminance / guide, FP32 baseline, and packed residual/weights.
// Packed xy = exposure residuals; zw = normalized highlight/shadow weights - 0.5.
// Centering weights improves half precision around the balanced-exposure region.
RWTexture2D<float2> compactOutput;
RWTexture2D<float> baseLightnessOutput;
RWTexture2D<float4> lightnessOutput;
#ifndef GATHER_UNSIGNED_SOURCE
#define GATHER_UNSIGNED_SOURCE 0
#endif

float logGuide(float3 rgb)
{
    return log2(max(dot(max(rgb, 0.0), float3(0.2126, 0.7152, 0.0722)), 1e-6));
}

void storeReducedLuma(uint2 pixel,float luminance,float guide)
{
    // Reuse the pre-exposure logarithm for both storage and all three brackets.
    float sourceLog=log2(max(luminance,1e-38));
    compactOutput[pixel]=float2(max(sourceLog,log2(1e-20))+globalEV,guide);
    luminance*=exp2(globalEV);
    // Share the input logarithm across all three brackets and avoid log(pow()).
    float3 logInputs=min(max(sourceLog+globalEV,log2(1e-38))+float3(-highlightEV,0,shadowEV),log2(zMaxInput));
    float3 numerator=exp2(logInputs*zParameters.x);
    float3 denominator=zParameters.z*exp2(logInputs*(zParameters.x*zParameters.y))+zParameters.w;
    float3 y=luminance>0 ? min(sqrt(numerator/denominator),zMaxLightness) : float3(0);
    float3 distance=y-0.5;
    float3 logWeight=-distance*distance/(2.0*sigma*sigma);
    float3 weights=exp2(logWeight-max(logWeight.x,max(logWeight.y,logWeight.z)));
    weights/=weights.x+weights.y+weights.z;
    baseLightnessOutput[pixel]=y.y;
    lightnessOutput[pixel]=float4(y.x-y.y,y.z-y.y,weights.xz-.5);

}

void storeReduced(uint2 pixel,float4 reduced)
{
    storeReducedLuma(pixel,dot(max(reduced.rgb,0.0),float3(0.2126,0.7152,0.0722)),reduced.a);
}

void reduceSampled(uint3 tid)
{
    uint w,h;
    compactOutput.GetDimensions(w,h);
    if(tid.x>=w || tid.y>=h) return;
    float4 sum=0;
    for(uint y=0; y<reductionRows; ++y)
        for(uint x=0; x<4; ++x)
        {
            float2 uv=(float2(tid.xy)+(float2(x,y)+0.5)/float(4))/float2(w,h);
            float3 rgb=max(fullSource.SampleLevel(linearSampler,uv,0).rgb,0.0);
            sum+=float4(rgb,logGuide(rgb));
        }
    float4 reduced=sum/float(4*4);
    storeReduced(tid.xy,reduced);
}

[shader("compute")]
[numthreads(8,8,1)]
void reduce_setup(uint3 tid : SV_DispatchThreadID) { reduceSampled(tid); }

[shader("compute")]
[numthreads(4,8,1)]
void reduce_setup_gather(uint3 tid : SV_DispatchThreadID)
{
    uint w,h,sw,sh;compactOutput.GetDimensions(w,h);fullSource.GetDimensions(sw,sh);
    if(tid.x>=w || tid.y>=h)return;
    if(sw!=w*4 || sh!=h*4){reduceSampled(tid);return;}
    float sumL=0,sumLog=0;
    for(uint y=0;y<2;y++)for(uint x=0;x<2;x++) {
        float2 uv=(float2(tid.xy)+(float2(x,y)+.5)/2.0)/float2(w,h);
#if GATHER_UNSIGNED_SOURCE
        // Finite R11G11B10 samples are already nonnegative. Other source
        // formats keep the clamped path; the host selects this specialization.
        float4 r=fullSource.GatherRed(linearSampler,uv);
        float4 g=fullSource.GatherGreen(linearSampler,uv);
        float4 b=fullSource.GatherBlue(linearSampler,uv);
#else
        float4 r=max(fullSource.GatherRed(linearSampler,uv),0.0);
        float4 g=max(fullSource.GatherGreen(linearSampler,uv),0.0);
        float4 b=max(fullSource.GatherBlue(linearSampler,uv),0.0);
#endif
        float4 luminance=float4(r)*.2126+float4(g)*.7152+float4(b)*.0722;
        sumL+=dot(luminance,float4(1));
        // Finite R11G11B10 input: each clamped luminance is in [1e-6,65535].
        // The four-value product stays normal in FP32 (1e-24 .. 1.85e19).
        // Preserve mean log luminance with one log per quad, modulo rounding.
        float4 positive=max(luminance,1e-6);
        sumLog+=log2((positive.x*positive.y)*(positive.z*positive.w));
    }
    storeReducedLuma(tid.xy,sumL/16.0,sumLog/16.0);
}



