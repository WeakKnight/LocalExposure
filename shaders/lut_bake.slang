#include "tone_operator.slang"
RWTexture3D<float4> bakedLut;
float maxInput;
float knee;
uint size;

[shader("compute")]
[numthreads(4, 4, 4)]
void bake_lut(uint3 tid : SV_DispatchThreadID)
{
    if (any(tid >= size)) return;
    float3 encoded = float3(tid) / float(size - 1);
    float3 color = knee * (exp2(encoded * log2(1.0 + maxInput / knee)) - 1.0);
    bakedLut[tid] = float4(toneOperator(color), 1.0);
}
