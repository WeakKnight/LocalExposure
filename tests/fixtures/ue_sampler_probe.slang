Texture2D<float> inputTexture;
SamplerState linearSampler;
RWTexture2D<float> outputTexture;

[shader("compute")]
[numthreads(64, 1, 1)]
void sample_probe(uint3 tid : SV_DispatchThreadID)
{
    uint w, h;
    outputTexture.GetDimensions(w, h);
    if (tid.x >= w) return;
    float t = (float(tid.x) + 0.37) / float(w);
    outputTexture[tid.xy] = inputTexture.SampleLevel(linearSampler, float2((0.5 + t) / 2.0, 0.5), 0);
}
