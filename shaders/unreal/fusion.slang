#include "common.slang"
Texture2D<float4> hdrSource;
RWTexture2D<float4> exposuresOutput;
RWTexture2D<float4> weightsOutput;
float targetLuminance;

[shader("compute")]
[numthreads(8, 8, 1)]
void setup_fusion(uint3 tid : SV_DispatchThreadID)
{
    uint w, h;
    exposuresOutput.GetDimensions(w, h);
    if (tid.x >= w || tid.y >= h) return;
    float lum = eyeLuminance(hdrSource[tid.xy].rgb / preExposure * exp2(globalEV));
    float3 y = float3(fusionLightnessUE(lum),
        fusionLightnessUE(lum * exp2(-6.0 * (1.0 - highlightContrast))),
        fusionLightnessUE(lum * exp2(6.0 * (1.0 - shadowContrast))));
    float3 d = y - targetLuminance;
    float3 weights = exp2(-d * d / (2.0 * 0.2 * 0.2));
    weights /= dot(weights, float3(1.0));
    exposuresOutput[tid.xy] = float4(y, 0.0);
    weightsOutput[tid.xy] = float4(weights, 0.0);
}

Texture2D<float4> fineLuminance;
Texture2D<float4> coarseLuminance;
Texture2D<float4> layerWeights;
Texture2D<float4> previousResult;
SamplerState linearSampler;
RWTexture2D<float4> reconstructionOutput;
bool isCoarsest;

[shader("compute")]
[numthreads(8, 8, 1)]
void blend_fusion(uint3 tid : SV_DispatchThreadID)
{
    uint w, h;
    reconstructionOutput.GetDimensions(w, h);
    if (tid.x >= w || tid.y >= h) return;
    float2 uv = (float2(tid.xy) + 0.5) / float2(w, h);
    float3 weights = layerWeights[tid.xy].rgb;
    weights /= dot(weights, float3(1.0));
    float3 detail = fineLuminance[tid.xy].rgb;
    float previous = 0.0;
    if (!isCoarsest)
    {
        detail -= coarseLuminance.SampleLevel(linearSampler, uv, 0).rgb;
        previous = previousResult.SampleLevel(linearSampler, uv, 0).r;
    }
    reconstructionOutput[tid.xy] = float4(previous + dot(detail, weights), 0.0, 0.0, 0.0);
}
