Texture2D<float4> inputTexture;
RWTexture2D<float4> outputTexture;
SamplerState linearSampler;
bool highQuality;

[shader("compute")]
[numthreads(8, 8, 1)]
void downsample_ue(uint3 tid : SV_DispatchThreadID)
{
    uint w, h, iw, ih;
    outputTexture.GetDimensions(w, h);
    inputTexture.GetDimensions(iw, ih);
    if (tid.x >= w || tid.y >= h) return;
    float2 uv = (float2(tid.xy) + 0.5) / float2(w, h);
    float4 result;
    if (highQuality)
    {
        float2 texel = 1.0 / float2(iw, ih);
        result = inputTexture.SampleLevel(linearSampler, uv + texel * float2(-1, -1), 0);
        result += inputTexture.SampleLevel(linearSampler, uv + texel * float2(1, -1), 0);
        result += inputTexture.SampleLevel(linearSampler, uv + texel * float2(-1, 1), 0);
        result += inputTexture.SampleLevel(linearSampler, uv + texel * float2(1, 1), 0);
        result *= 0.25;
    }
    else result = inputTexture.SampleLevel(linearSampler, uv, 0);
    outputTexture[tid.xy] = result;
}
