// Display only. Tone mapping is evaluated at source resolution before filtering.
float toSRGB(float x)
{
    return x <= 0.0031308 ? 12.92 * x : 1.055 * pow(x, 1.0 / 2.4) - 0.055;
}

Texture2D<float4> source;
Texture2D<float4> finalColor;
Texture2D<float> localExposure;
SamplerState linearSampler;
RWTexture2D<float4> output;
uint viewMode; // 0: fusion, 1: compare, 2: local exposure EV

[shader("compute")]
[numthreads(8, 8, 1)]
void compute_main(uint3 tid : SV_DispatchThreadID)
{
    uint width, height, srcWidth, srcHeight;
    output.GetDimensions(width, height);
    source.GetDimensions(srcWidth, srcHeight);
    if (tid.x >= width || tid.y >= height) return;
    float2 viewportSize = float2(width, height);
    float2 pixel = float2(tid.xy) + 0.5;
    float scale = min(viewportSize.x / srcWidth, viewportSize.y / srcHeight);
    float2 imageSize = float2(srcWidth, srcHeight) * scale;
    float2 uv = (pixel - (viewportSize - imageSize) * 0.5) / imageSize;
    if (any(uv < 0.0) || any(uv > 1.0))
    {
        output[tid.xy] = float4(0.025, 0.025, 0.025, 1.0);
        return;
    }
    if (viewMode == 2)
    {
        float ev = log2(max(localExposure.SampleLevel(linearSampler, uv, 0), 1e-20));
        output[tid.xy] = float4(float3(saturate(0.5 + ev / 12.0)), 1.0);
        return;
    }
    float3 mapped = finalColor.SampleLevel(linearSampler, uv, 0).rgb;
    if (viewMode == 1 && uv.x < 0.5)
        mapped = source.SampleLevel(linearSampler, uv, 0).rgb;
    output[tid.xy] = float4(toSRGB(mapped.r), toSRGB(mapped.g), toSRGB(mapped.b), 1.0);
}
