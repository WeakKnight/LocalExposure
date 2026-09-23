#include "tone_operator.slang"

Texture2D<float4> fullSource;
SamplerState linearSampler;
RWTexture2D<float4> reducedOutput;

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
    for (uint y = 0; y < 4; ++y)
        for (uint x = 0; x < 4; ++x)
        {
            float2 uv = (float2(tid.xy) + (float2(x, y) + 0.5) / 4.0) / float2(w, h);
            float3 rgb = max(fullSource.SampleLevel(linearSampler, uv, 0).rgb, 0.0);
            sum += float4(rgb, logGuide(rgb));
        }
    reducedOutput[tid.xy] = sum / 16.0;
}

Texture2D<float4> reducedSource;
Texture2D<float> lowExposure;
RWTexture2D<float2> coefficientOutput;

// Fast guided filter: fit EV = a * log-luminance + b in a 5x5 low-res window.
// Guide was averaged in log space separately from linear HDR downsampling.
[shader("compute")]
[numthreads(8, 8, 1)]
void fit_coefficients(uint3 tid : SV_DispatchThreadID)
{
    uint w, h;
    coefficientOutput.GetDimensions(w, h);
    if (tid.x >= w || tid.y >= h) return;
    float center = reducedSource[tid.xy].a;
    // Only per-sample centered values/products use half. Accumulate all 25
    // samples and solve covariance/variance in float to avoid cancellation.
    // Keep a,b and the final a*guide+b float as well.
    float meanG = 0, meanE = 0, meanGG = 0, meanGE = 0;
    for (int y = -2; y <= 2; ++y)
        for (int x = -2; x <= 2; ++x)
        {
            int2 p = clamp(int2(tid.xy) + int2(x, y), int2(0), int2(w-1, h-1));
            // Subtract in float before narrowing: small guide differences
            // would disappear if the two absolute log values were half.
            half g = half(reducedSource[p].a - center);
            half e = half(log2(max(lowExposure[p], 1e-20)));
            meanG += g; meanE += e; meanGG += float(g*g); meanGE += float(g*e);
        }
    meanG /= 25; meanE /= 25; meanGG /= 25; meanGE /= 25;
    float variance = max(meanGG - meanG*meanG, 0.0);
    float a = (meanGE - meanG*meanE) / (variance + 0.04); // epsilon: EV^2
    coefficientOutput[tid.xy] = float2(a, meanE - a*(meanG + center));
}

Texture2D<float2> coefficients;
RWTexture2D<float2> averagedOutput;

[shader("compute")]
[numthreads(8, 8, 1)]
void average_coefficients(uint3 tid : SV_DispatchThreadID)
{
    uint w, h;
    averagedOutput.GetDimensions(w, h);
    if (tid.x >= w || tid.y >= h) return;
    float2 sum = 0;
    for (int y = -2; y <= 2; ++y)
        for (int x = -2; x <= 2; ++x)
            sum += coefficients[clamp(int2(tid.xy) + int2(x, y), int2(0), int2(w-1, h-1))];
    averagedOutput[tid.xy] = sum / 25.0;
}

Texture2D<float2> averagedCoefficients;
RWTexture2D<float> fullExposureOutput;
RWTexture2D<float4> baseOutput;
RWTexture2D<float4> colorOutput;
float globalEV;
bool guided;

// Full resolution only applies exposure and tone mapping, never runs Fusion
// or the 10-step exposure search. Full-res reference bypasses guided filtering.
[shader("compute")]
[numthreads(8, 8, 1)]
void apply_exposure(uint3 tid : SV_DispatchThreadID)
{
    uint w, h;
    colorOutput.GetDimensions(w, h);
    if (tid.x >= w || tid.y >= h) return;
    float3 hdr = max(fullSource[tid.xy].rgb, 0.0);
    float multiplier;
    if (guided)
    {
        float2 uv = (float2(tid.xy) + 0.5) / float2(w, h);
        float2 ab = averagedCoefficients.SampleLevel(linearSampler, uv, 0);
        multiplier = exp2(clamp(ab.x*logGuide(hdr) + ab.y, -12.0, 12.0));
    }
    else multiplier = lowExposure[tid.xy];
    float3 color = hdr * exp2(globalEV);
    fullExposureOutput[tid.xy] = multiplier;
    baseOutput[tid.xy] = float4(toneOperator(color), 1.0);
    colorOutput[tid.xy] = float4(toneOperator(color * multiplier), 1.0);
}
