// Curve-only UE compatibility for Bart's independent pyramid schedules.
// Use the audited UE equations, using UE's default equal-RGB luminance metric.
#include "unreal/common.slang"
float highlightEV;
float shadowEV;
float sigma;

float bartFilmLuminance(float3 hdr)
{
    // UE's default eye-luminance floor, after global exposure.
    return max(dot(max(hdr, 0.0), float3(1.0/3.0)) * exp2(globalEV), exp2(-8.0));
}

void bartFilmSamples(float luminance, out float3 lightness, out float3 weights)
{
    // Dark, base, bright order matches Bart's compact residual representation.
    lightness = float3(fusionLightnessUE(luminance * exp2(-highlightEV)),
                      fusionLightnessUE(luminance),
                      fusionLightnessUE(luminance * exp2(shadowEV)));
    float3 d = lightness - .5;
    float3 logWeight = -d*d/(2.0*sigma*sigma);
    weights = exp2(logWeight-max(logWeight.x,max(logWeight.y,logWeight.z)));
    weights /= weights.x+weights.y+weights.z;
}
