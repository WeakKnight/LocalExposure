#include "tone_operator.slang"

Texture3D<float4> toneLut;
SamplerState lutSampler;
float lutMaxInput;
float lutKnee;
uint lutSize;

float3 proxyToneOperator(float3 color)
{
    // Fixed HDR domain: use the boundary nodes for out-of-range channels.
    color = clamp(color, 0.0, lutMaxInput);
    float3 encoded = log2(1.0 + color / lutKnee) / log2(1.0 + lutMaxInput / lutKnee);
    // Nodes include both domain endpoints; SampleLevel expects texel centers.
    float3 uv = (encoded * float(lutSize - 1) + 0.5) / float(lutSize);
    return toneLut.SampleLevel(lutSampler, uv, 0).rgb;
}
