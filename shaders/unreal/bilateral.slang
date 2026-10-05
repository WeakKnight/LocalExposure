#include "common.slang"
Texture2D<float4> hdrSource;
SamplerState pointSampler;
RWTexture3D<float2> gridOutput;
groupshared uint tileHistogram[32][8][8];

uint packPair(float weight, float weightedPosition)
{
    return ((uint(weight * 512.0) & 0xffff) << 16) | (uint(weightedPosition * 512.0) & 0xffff);
}

[shader("compute")]
[numthreads(8, 8, 1)]
void build_grid(uint3 group : SV_GroupID, uint3 thread : SV_GroupThreadID, uint index : SV_GroupIndex)
{
    for (uint b = 0; b < 32; ++b) tileHistogram[b][thread.x][thread.y] = 0;
    GroupMemoryBarrierWithGroupSync();
    uint w, h;
    hdrSource.GetDimensions(w, h);
    for (uint y = 0; y < 64; y += 16)
    for (uint x = 0; x < 64; x += 16)
    {
        uint2 pixel = group.xy * 64 + uint2(x, y) + thread.xy * 2;
        // Match UE: a partial quad is omitted, including the final odd row.
        if (pixel.x + 1 < w && pixel.y + 1 < h)
        {
            float2 uv = (float2(pixel) + 1.0) / float2(w, h);
            float4 r = hdrSource.GatherRed(pointSampler, uv) / preExposure;
            float4 g = hdrSource.GatherGreen(pointSampler, uv) / preExposure;
            float4 b = hdrSource.GatherBlue(pointSampler, uv) / preExposure;
            for (uint i = 0; i < 4; ++i)
            {
                float position = histogramPosition(log2(eyeLuminance(float3(r[i], g[i], b[i]))));
                float bucket = saturate(position) * 31.0;
                uint lo = min(uint(bucket), 31u);
                uint hi = min(lo + 1, 31u);
                float alpha = frac(bucket);
                // Packed fixed point and its carry behavior are intentional.
                InterlockedAdd(tileHistogram[lo][thread.x][thread.y], packPair(1.0 - alpha, position * (1.0 - alpha)));
                InterlockedAdd(tileHistogram[hi][thread.x][thread.y], packPair(alpha, position * alpha));
            }
        }
    }
    GroupMemoryBarrierWithGroupSync();
    if (index < 32)
    {
        float sum = 0.0;
        float sumLum = 0.0;
        for (uint y = 0; y < 8; ++y)
        for (uint x = 0; x < 8; ++x)
        {
            uint packed = tileHistogram[index][x][y];
            float weight = float(packed >> 16) / 512.0;
            float moment = float(packed & 0xffff) / 512.0;
            sum += weight;
            sumLum += moment * (histogramMax - histogramMin) + weight * histogramMin;
        }
        gridOutput[uint3(group.xy, index)] = float2(sumLum, sum);
    }
}

RWTexture2D<float> logOutput;
[shader("compute")]
[numthreads(8, 8, 1)]
void setup_log(uint3 tid : SV_DispatchThreadID)
{
    uint w, h;
    logOutput.GetDimensions(w, h);
    if (tid.x >= w || tid.y >= h) return;
    logOutput[tid.xy] = log2(eyeLuminance(hdrSource[tid.xy].rgb / preExposure));
}

Texture2D<float> blurInput;
RWTexture2D<float> blurOutput;
StructuredBuffer<float2> blurTaps;
uint tapCount;
float2 blurAxis;
SamplerState mirrorSampler;

[shader("compute")]
[numthreads(8, 8, 1)]
void blur_log(uint3 tid : SV_DispatchThreadID)
{
    uint w, h;
    blurOutput.GetDimensions(w, h);
    if (tid.x >= w || tid.y >= h) return;
    float2 uv = (float2(tid.xy) + 0.5) / float2(w, h);
    float sum = 0.0;
    for (uint i = 0; i < tapCount; ++i)
        sum += blurInput.SampleLevel(mirrorSampler, uv + blurAxis * blurTaps[i].x, 0) * blurTaps[i].y;
    blurOutput[tid.xy] = sum;
}
