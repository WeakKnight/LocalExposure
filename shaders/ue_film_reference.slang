// Full-resolution control: evaluate three exposures independently, no LUT.
#include "ue_film_curve.slang"
Texture2D<float4> hdrSource;
RWTexture2D<float4> luminanceOutput;
RWTexture2D<float4> weightOutput;
Texture2D<float> fusedLightness;
RWTexture2D<half> exposureOutput;

[shader("compute")]
[numthreads(8,8,1)]
void setup_weights(uint3 tid:SV_DispatchThreadID)
{
    uint w,h; weightOutput.GetDimensions(w,h);
    if(tid.x>=w || tid.y>=h) return;
    float3 y,weights;
    bartFilmSamples(bartFilmLuminance(hdrSource[tid.xy].rgb),y,weights);
    luminanceOutput[tid.xy]=float4(y,1);
    weightOutput[tid.xy]=float4(weights,1);
}

[shader("compute")]
[numthreads(8,8,1)]
void convert_exposure(uint3 tid:SV_DispatchThreadID)
{
    uint w,h; exposureOutput.GetDimensions(w,h);
    if(tid.x>=w || tid.y>=h) return;
    // Preserve UE's clamp/fixed inverse, including nonidentity at zero brackets.
    exposureOutput[tid.xy]=half(fusionExposureUE(
        bartFilmLuminance(hdrSource[tid.xy].rgb),fusedLightness[tid.xy]));
}
