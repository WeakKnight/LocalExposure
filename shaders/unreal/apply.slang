#include "common.slang"
#include "../tone_operator.slang"
Texture2D<float4> hdrSource;
Texture2D<float4> fusedResult;
Texture3D<float2> bilateralGrid;
Texture2D<float> blurredLog;
float2 gridUVScale;
SamplerState linearSampler;
RWTexture2D<half4> colorOutput;
RWTexture2D<half4> baseOutput;
RWTexture2D<float> exposureOutput;

float localMultiplier(uint2 pixel, float2 uv, uint method)
{
    float3 rgb = hdrSource[pixel].rgb / preExposure;
    if (method == 1) return fusionExposureUE(eyeLuminance(rgb * exp2(globalEV)), fusedResult.SampleLevel(linearSampler, uv, 0).r);
    if (method == 2)
    {
        float logLum = log2(eyeLuminance(rgb));
        float z = (histogramPosition(logLum) * 31.0 + 0.5) / 32.0;
        float2 grid = bilateralGrid.SampleLevel(linearSampler, float3(uv * gridUVScale, z), 0);
        float blurred = blurredLog.SampleLevel(linearSampler, uv, 0);
        float bilateral = grid.y < 0.001 ? blurred : grid.x / grid.y;
        float base = lerp(bilateral, blurred, blurredBlend) + globalEV;
        return bilateralExposureUE(logLum + globalEV, base);
    }
    return 1.0;
}

void applyPixel(uint2 pixel, uint method, bool inspect)
{
    uint w, h;
    colorOutput.GetDimensions(w, h);
    if (pixel.x >= w || pixel.y >= h) return;
    float2 uv = (float2(pixel) + 0.5) / float2(w, h);
    float multiplier = localMultiplier(pixel, uv, method);
    float3 hdr = hdrSource[pixel].rgb / preExposure * exp2(globalEV);
    colorOutput[pixel] = half4(half3(toneOperator(hdr * multiplier)), half(1.0));
    if (inspect)
    {
        baseOutput[pixel] = half4(half3(toneOperator(hdr)), half(1.0));
        exposureOutput[pixel] = multiplier;
    }
}

#define APPLY_ENTRY(NAME, METHOD, INSPECT) \
    [shader("compute")] [numthreads(8, 8, 1)] \
    void NAME(uint3 tid : SV_DispatchThreadID) { applyPixel(tid.xy, METHOD, INSPECT); }
APPLY_ENTRY(apply_baseline, 0, false)
APPLY_ENTRY(apply_fusion, 1, false)
APPLY_ENTRY(apply_bilateral, 2, false)
APPLY_ENTRY(inspect_fusion, 1, true)
APPLY_ENTRY(inspect_bilateral, 2, true)
