#include "tone_operator.slang"
#include "zcurve.slang"
Texture2D<float4> calibrationInput;
RWTexture2D<float4> calibrationOutput;

[shader("compute")]
[numthreads(8, 8, 1)]
void sample_operator(uint3 tid : SV_DispatchThreadID)
{
    uint w, h;
    calibrationOutput.GetDimensions(w, h);
    if (tid.x >= w || tid.y >= h) return;
    calibrationOutput[tid.xy] = float4(toneOperator(calibrationInput[tid.xy].rgb), 1.0);
}

[shader("compute")]
[numthreads(8, 8, 1)]
void sample_curve(uint3 tid : SV_DispatchThreadID)
{
    uint w, h;
    calibrationOutput.GetDimensions(w, h);
    if (tid.x >= w || tid.y >= h) return;
    float lightness = fusionLightness(calibrationInput[tid.xy].x);
    calibrationOutput[tid.xy] = float4(lightness, inverseFusionLightness(lightness),
        inverseFusionLightness(calibrationInput[tid.xy].y), 1.0);
}
