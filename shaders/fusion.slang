#include "lut_proxy.slang"
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

float mappedLuminance(float3 color)
{
    return dot(proxyToneOperator(color), float3(0.2126, 0.7152, 0.0722));
}

[shader("compute")]
[numthreads(8, 8, 1)]
void convert_exposure(uint3 tid : SV_DispatchThreadID)
{
    uint width, height;
    exposureOutput.GetDimensions(width, height);
    if (tid.x >= width || tid.y >= height) return;
    float3 color = max(hdrSource[tid.xy].rgb, 0.0) * exp2(globalEV);
    float lightness = saturate(fusedLightness[tid.xy]);
    float target = lightness * lightness; // undo perceptual sqrt
    float baseline = mappedLuminance(color);
    half multiplier = half(1.0);
    // Solve one scalar exposure along the RGB ray using the same LUT as setup.
    // Only the final color evaluates the real operator.
    // Preserve identity when target already matches, including clipped whites.
    if (max(color.x, max(color.y, color.z)) > 1e-12 && abs(target - baseline) > 2e-6)
    {
        // These bounds and the first 10 bisection midpoints are exactly
        // representable in half (multiples of 24/1024 within [-12,12]).
        // Revisit this type if the search range or iteration count changes.
        half lo = half(-12.0), hi = half(12.0);
        // 24 / 2^10 = 0.0234375 EV final search interval.
        for (uint i = 0; i < 10; ++i)
        {
            half mid = (lo + hi) * half(0.5);
            if (mappedLuminance(color * exp2(float(mid))) < target) lo = mid;
            else hi = mid;
        }
        // Keep the eleventh midpoint and exp2 float; only narrow their result.
        multiplier = half(exp2((float(lo) + float(hi)) * 0.5));
    }
    exposureOutput[tid.xy] = multiplier;
}
