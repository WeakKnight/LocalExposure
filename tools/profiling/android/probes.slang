// Diagnostic controls only. Never used by the production Fusion pipeline.
#include "tone_operator.slang"
#ifndef PROBE_GROUP_X
#define PROBE_GROUP_X 8
#define PROBE_GROUP_Y 8
#endif
float globalEV;
Texture2D<float4> inputTexture;
RWTexture2D<half4> outputTexture;

[shader("compute")]
[numthreads(PROBE_GROUP_X, PROBE_GROUP_Y, 1)]
void copy_probe(uint3 tid : SV_DispatchThreadID)
{
    uint w, h;
    outputTexture.GetDimensions(w, h);
    if (tid.x >= w || tid.y >= h) return;
    float3 color = max(inputTexture[tid.xy].rgb, 0.0) * exp2(globalEV);
    outputTexture[tid.xy] = half4(half3(color), half(1.0));
}

[shader("compute")]
[numthreads(PROBE_GROUP_X, PROBE_GROUP_Y, 1)]
void fill_probe(uint3 tid : SV_DispatchThreadID)
{
    uint w, h;
    outputTexture.GetDimensions(w, h);
    if (tid.x >= w || tid.y >= h) return;
    outputTexture[tid.xy] = half4(0.25, 0.5, 0.75, 1.0);
}

[shader("compute")]
[numthreads(PROBE_GROUP_X, PROBE_GROUP_Y, 1)]
void empty_probe(uint3 tid : SV_DispatchThreadID)
{
}
