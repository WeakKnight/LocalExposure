// Independent full-resolution reference application; no Guided reconstruction.
#include "tone_operator.slang"
Texture2D<float4> fullSource;
Texture2D<half> lowExposure;
RWTexture2D<half> fullExposureOutput;
RWTexture2D<half4> baseOutput;
RWTexture2D<half4> colorOutput;
float globalEV;

// Production: one final linear SDR output, no comparison/EV debug outputs.
[shader("compute")]
[numthreads(8, 8, 1)]
void apply_exposure_production(uint3 tid : SV_DispatchThreadID)
{
    uint w, h;
    colorOutput.GetDimensions(w, h);
    if (tid.x >= w || tid.y >= h) return;
    float3 hdr = max(fullSource[tid.xy].rgb, 0.0);
    half multiplier = lowExposure[tid.xy];
    float3 color = hdr * exp2(globalEV);
    colorOutput[tid.xy] = half4(half3(toneOperator(color * float(multiplier))), half(1.0));
}

// Matched full-resolution baseline for measuring local-exposure overhead.
[shader("compute")]
[numthreads(8, 8, 1)]
void tonemap_baseline(uint3 tid : SV_DispatchThreadID)
{
    uint w, h;
    colorOutput.GetDimensions(w, h);
    if (tid.x >= w || tid.y >= h) return;
    float3 color = max(fullSource[tid.xy].rgb, 0.0) * exp2(globalEV);
    colorOutput[tid.xy] = half4(half3(toneOperator(color)), half(1.0));
}

// Viewer only: additionally writes the comparison color and exposure map.
[shader("compute")]
[numthreads(8, 8, 1)]
void apply_exposure(uint3 tid : SV_DispatchThreadID)
{
    uint w, h;
    colorOutput.GetDimensions(w, h);
    if (tid.x >= w || tid.y >= h) return;
    float3 hdr = max(fullSource[tid.xy].rgb, 0.0);
    half multiplier = lowExposure[tid.xy];
    float3 color = hdr * exp2(globalEV);
    fullExposureOutput[tid.xy] = multiplier;
    baseOutput[tid.xy] = half4(half3(toneOperator(color)), half(1.0));
    colorOutput[tid.xy] = half4(half3(toneOperator(color * float(multiplier))), half(1.0));
}
