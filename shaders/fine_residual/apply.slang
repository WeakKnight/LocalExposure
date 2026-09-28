// Reconstruct missing fine residuals, then invert lightness at full resolution.
// No Guided fitting: averagedCoefficients binds the low-resolution residual map.
#include "tone_operator.slang"
#include "zcurve.slang"
Texture2D<float4> fullSource;
SamplerState linearSampler;
Texture2D<float2> averagedCoefficients;
Texture2D<float4> lowResidual;
Texture1D<float4> fineLookup;
RWTexture2D<half4> colorOutput;
float globalEV;
bool guided;

// Shared by the production entry and the viewer's diagnostic wrapper.
half exposureMultiplier(uint2 pixel, uint2 size, float3 hdr)
{
    // 2^-12 .. 2^12 is entirely within half's normal finite range. Round
    // explicitly so the HDR multiplication and saved exposure use one value.
    half multiplier;
    if (guided)
    {
        float2 uv = (float2(pixel) + 0.5) / float2(size);
        float2 ab = averagedCoefficients.SampleLevel(linearSampler, uv, 0);
        float luminance=dot(hdr,float3(.2126,.7152,.0722))*exp2(globalEV);
        float logL=log2(max(luminance,exp2(-40.)));
        float coord=(saturate((logL+40.)/80.)*2047.+.5)/2048.;
        float4 f=fineLookup.SampleLevel(linearSampler,coord,0);
        float2 low=lowResidual.SampleLevel(linearSampler,uv,0).xy;
        float target=clamp(f.x+ab.x-dot(low,f.yz),0.,zMaxLightness);
        multiplier=half(clamp(inverseFusionLightness(target)/max(luminance,1e-12),exp2(-12.),exp2(12.)));
    }
    else multiplier = half(1.0);
    return multiplier;
}

// Production: one final linear SDR output, no comparison/EV debug outputs.
[shader("compute")]
[numthreads(8, 8, 1)]
void apply_exposure_production(uint3 tid : SV_DispatchThreadID)
{
    uint w, h;
    colorOutput.GetDimensions(w, h);
    if (tid.x >= w || tid.y >= h) return;
    float3 hdr = max(fullSource[tid.xy].rgb, 0.0);
    half multiplier = exposureMultiplier(tid.xy, uint2(w, h), hdr);
    float3 color = hdr * exp2(globalEV);
    colorOutput[tid.xy] = half4(half3(toneOperator(color * float(multiplier))), half(1.0));
}

