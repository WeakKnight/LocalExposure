#include "lut_proxy.slang"

Texture2D<float4> calibrationInput;
RWTexture2D<float4> calibrationOutput;

[shader("compute")]
[numthreads(8, 8, 1)]
void sample_operator(uint3 tid : SV_DispatchThreadID)
{
    uint width, height;
    calibrationOutput.GetDimensions(width, height);
    if (tid.x >= width || tid.y >= height) return;
    calibrationOutput[tid.xy] = float4(toneOperator(calibrationInput[tid.xy].rgb), 1.0);
}

[shader("compute")]
[numthreads(8, 8, 1)]
void sample_proxy(uint3 tid : SV_DispatchThreadID)
{
    uint width, height;
    calibrationOutput.GetDimensions(width, height);
    if (tid.x >= width || tid.y >= height) return;
    calibrationOutput[tid.xy] = float4(proxyToneOperator(calibrationInput[tid.xy].rgb), 1.0);
}
