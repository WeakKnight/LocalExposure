// Documentation-only readback. Reuse the exact production exposure recovery.
#include "fine_residual/apply.slang"
RWTexture2D<float4> weightsAndEV;

[shader("compute")]
[numthreads(8, 8, 1)]
void inspect_fusion(uint3 tid : SV_DispatchThreadID)
{
    uint w, h;
    weightsAndEV.GetDimensions(w, h);
    if (tid.x >= w || tid.y >= h) return;
    float2 uv = (float2(tid.xy) + .5) / float2(w, h);
    float2 outerWeights = lowResidual.SampleLevel(linearSampler, uv, 0).zw + .5;
    float3 weights = float3(outerWeights.x, 1.0 - outerWeights.x - outerWeights.y, outerWeights.y);
    float3 hdr = max(fullSource[tid.xy].rgb, 0.0);
    float ev = log2(float(exposureMultiplier(tid.xy, uint2(w, h), hdr)));
    weightsAndEV[tid.xy] = float4(weights, ev);
}
