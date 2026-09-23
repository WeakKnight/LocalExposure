#include "zcurve.slang"
Texture2D<float4> fineLuminance;
Texture2D<float4> coarseLuminance;
Texture2D<float4> layerWeights;
Texture2D<float> previousResult;
SamplerState linearSampler;
RWTexture2D<float> reconstructionOutput;
bool isCoarsest;

// Evaluate the weighted Laplacian inline during coarse-to-fine reconstruction.
// The coarsest level is a weighted base, not a difference band.
[shader("compute")]
[numthreads(8, 8, 1)]
void reconstruct(uint3 tid : SV_DispatchThreadID)
{
    uint width, height;
    reconstructionOutput.GetDimensions(width, height);
    if (tid.x >= width || tid.y >= height) return;
    float2 uv = (float2(tid.xy) + 0.5) / float2(width, height);
    // Float subtraction/accumulation preserves small signed detail bands.
    float3 detail = fineLuminance[tid.xy].rgb;
    if (!isCoarsest)
        detail -= coarseLuminance.SampleLevel(linearSampler, uv, 0).rgb;
    float3 w = layerWeights[tid.xy].rgb;
    // Float normalization is required before exposure inversion.
    w /= max(w.x + w.y + w.z, 1e-20);
    float3 contribution = detail * w;
    float value = contribution.x + contribution.y + contribution.z;
    if (!isCoarsest)
        value += previousResult.SampleLevel(linearSampler, uv, 0);
    // Keep signed/overshooting intermediate values until final conversion.
    reconstructionOutput[tid.xy] = value;
}

Texture2D<float4> hdrSource;
Texture2D<float> fusedLightness;
RWTexture2D<half> exposureOutput;
float globalEV;

[shader("compute")]
[numthreads(8, 8, 1)]
void convert_exposure(uint3 tid : SV_DispatchThreadID)
{
    uint width, height;
    exposureOutput.GetDimensions(width, height);
    if (tid.x >= width || tid.y >= height) return;
    float luminance = dot(max(hdrSource[tid.xy].rgb, 0.0), float3(0.2126, 0.7152, 0.0722)) * exp2(globalEV);
    float target = clamp(fusedLightness[tid.xy], 0.0, zMaxLightness);
    float baseline = fusionLightness(luminance);
    half multiplier = half(1.0);
    // The same scalar curve defines both setup and inverse reconstruction.
    // Preserve identity near equality, including domain-clamped highlights.
    if (luminance > 1e-12 && abs(target - baseline) > 2e-6)
    {
        float targetLuminance = inverseFusionLightness(target);
        multiplier = half(clamp(targetLuminance / luminance, exp2(-12.0), exp2(12.0)));
    }
    exposureOutput[tid.xy] = multiplier;
}
