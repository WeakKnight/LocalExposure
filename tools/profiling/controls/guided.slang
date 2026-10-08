#include "tone_operator.slang"

Texture2D<float4> fullSource;
SamplerState linearSampler;
RWTexture2D<float4> reducedOutput;
// Always bound to 4 by the host. A runtime outer bound avoids scheduling all
// 16 samples together on Mali (G720: 64 registers + spills -> 32, no spills).
// Keep this a uniform, not a specialization constant. Sample/add order is unchanged.
uint reductionRows;

float logGuide(float3 rgb)
{
    // HDR (including 65535) exceeds half; retain precision near the dark floor.
    return log2(max(dot(max(rgb, 0.0), float3(0.2126, 0.7152, 0.0722)), 1e-6));
}

// Area-like 4x4 integration at normalized cell centers. Exact 4x4 box for
// divisible dimensions; bilinear samples support odd and tiny input sizes.
[shader("compute")]
[numthreads(8, 8, 1)]
void reduce_source(uint3 tid : SV_DispatchThreadID)
{
    uint w, h;
    reducedOutput.GetDimensions(w, h);
    if (tid.x >= w || tid.y >= h) return;
    float4 sum = 0;
    for (uint y = 0; y < reductionRows; ++y)
        for (uint x = 0; x < 4; ++x)
        {
            float2 uv = (float2(tid.xy) + (float2(x, y) + 0.5) / 4.0) / float2(w, h);
            float3 rgb = max(fullSource.SampleLevel(linearSampler, uv, 0).rgb, 0.0);
            sum += float4(rgb, logGuide(rgb));
        }
    reducedOutput[tid.xy] = sum / 16.0;
}

Texture2D<float4> reducedSource;
Texture2D<half> lowExposure;
RWTexture2D<float2> coefficientOutput;
// 12 populated columns with pitch 13: same samples, lower A730 address-code
// instruction count. Keep guide FP32 and EV half-rounded as before.
groupshared float2 fitTile[156];

float2 solveFit(uint3 localID)
{
    float center = fitTile[(localID.y + 2) * 13 + localID.x + 2].x;
    // Only per-sample centered values/products use half. Accumulate all 25
    // samples and solve covariance/variance in float to avoid cancellation.
    // Form the cancellation-sensitive differences in float before narrowing.
    // Intercept construction, coefficient storage and final a*guide+b stay float.
    float meanG = 0, meanE = 0, meanGG = 0, meanGE = 0;
    for (int y = -2; y <= 2; ++y)
        for (int x = -2; x <= 2; ++x)
        {
            uint index = (localID.y + y + 2) * 13 + localID.x + x + 2;
            // Subtract in float before narrowing: small guide differences
            // would disappear if the two absolute log values were half.
            float2 cached = fitTile[index];
            half g = half(cached.x - center);
            half e = half(cached.y);
            meanG += g; meanE += e; meanGG += float(g*g); meanGE += float(g*e);
        }
    meanG /= 25; meanE /= 25; meanGG /= 25; meanGE /= 25;
    float variance = max(meanGG - meanG*meanG, 0.0);
    // Regularization keeps the denominator >= 0.04; the centered covariance
    // and regularized denominator can be narrowed before half division.
    half covariance = half(meanGE - meanG*meanE);
    half denominator = half(variance + 0.04); // epsilon: EV^2
    half a = covariance / denominator;
    return float2(float(a), meanE - float(a)*(meanG + center));
}

// Fast guided filter: fit EV = a * log-luminance + b in a 5x5 low-res window.
// Guide was averaged in log space separately from linear HDR downsampling.
[shader("compute")]
[numthreads(8, 8, 1)]
void fit_coefficients(uint3 tid : SV_DispatchThreadID, uint3 localID : SV_GroupThreadID,
                      uint3 groupID : SV_GroupID)
{
    uint w, h;
    coefficientOutput.GetDimensions(w, h);
    uint lane = localID.y * 8 + localID.x;
    for (uint i = lane; i < 144; i += 64)
    {
        int2 p = clamp(int2(groupID.xy * 8) + int2(i % 12, i / 12) - 2,
                       int2(0), int2(w-1, h-1));
        // Preserve the original half rounding before reusing the EV. Float
        // shared storage represents every resulting half value exactly.
        fitTile[(i / 12) * 13 + i % 12] = float2(reducedSource[p].a, float(half(log2(max(lowExposure[p], 1e-20)))));
    }
    GroupMemoryBarrierWithGroupSync();
    if (tid.x >= w || tid.y >= h) return;
    coefficientOutput[tid.xy] = solveFit(localID);
}

Texture2D<float2> coefficients;
RWTexture2D<float2> averagedOutput;
groupshared float2 coefficientTile[144]; // 8x8 output plus a 2-pixel halo.

[shader("compute")]
[numthreads(8, 8, 1)]
void average_coefficients(uint3 tid : SV_DispatchThreadID, uint3 localID : SV_GroupThreadID,
                          uint3 groupID : SV_GroupID)
{
    uint w, h;
    averagedOutput.GetDimensions(w, h);
    uint lane = localID.y * 8 + localID.x;
    for (uint i = lane; i < 144; i += 64)
    {
        int2 p = int2(groupID.xy * 8) + int2(i % 12, i / 12) - 2;
        coefficientTile[i] = coefficients[clamp(p, int2(0), int2(w-1, h-1))];
    }
    // Edge-group lanes must populate the halo before any lane exits.
    GroupMemoryBarrierWithGroupSync();
    if (tid.x >= w || tid.y >= h) return;
    float2 sum = 0;
    // Preserve the original FP32 row-major sum exactly; only the source of
    // each load changes. Do not split into separable sums or narrow the tile.
    for (int y = -2; y <= 2; ++y)
        for (int x = -2; x <= 2; ++x)
            sum += coefficientTile[(localID.y + y + 2) * 12 + localID.x + x + 2];
    averagedOutput[tid.xy] = sum / 25.0;
}

Texture2D<float2> averagedCoefficients;
RWTexture2D<half> fullExposureOutput;
RWTexture2D<half4> baseOutput;
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
        multiplier = half(exp2(clamp(ab.x*logGuide(hdr) + ab.y, -12.0, 12.0)));
    }
    else multiplier = half(lowExposure[pixel]);
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

// Matched full-resolution baseline for measuring local-exposure overhead.
[shader("compute")]
[numthreads(8, 8, 1)]
void tonemap_baseline(uint3 tid : SV_DispatchThreadID)
{
    uint w, h;
    colorOutput.GetDimensions(w, h);
    if (tid.x >= w || tid.y >= h) return;
    float3 color = max(fullSource[tid.xy].rgb, 0.0) * exp2(globalEV);
    colorOutput[tid.xy] = half4(half3(toneOperator(color)), half(1.0));
}

// Viewer only: additionally writes the comparison color and exposure map.
[shader("compute")]
[numthreads(8, 8, 1)]
void apply_exposure(uint3 tid : SV_DispatchThreadID)
{
    uint w, h;
    colorOutput.GetDimensions(w, h);
    if (tid.x >= w || tid.y >= h) return;
    float3 hdr = max(fullSource[tid.xy].rgb, 0.0);
    half multiplier = exposureMultiplier(tid.xy, uint2(w, h), hdr);
    float3 color = hdr * exp2(globalEV);
    fullExposureOutput[tid.xy] = multiplier;
    baseOutput[tid.xy] = half4(half3(toneOperator(color)), half(1.0));
    colorOutput[tid.xy] = half4(half3(toneOperator(color * float(multiplier))), half(1.0));
}
