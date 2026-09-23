// Frozen reduction implementation before the Mali spill optimization.

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

