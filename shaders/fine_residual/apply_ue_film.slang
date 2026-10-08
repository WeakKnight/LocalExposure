#include "../tone_operator.slang"
#include "../ue_film_curve.slang"
Texture2D<float4> fullSource;
Texture2D<float2> averagedCoefficients;
Texture2D<float4> lowResidual;
SamplerState linearSampler;
RWTexture2D<half4> colorOutput;
RWTexture2D<half4> baseOutput;
RWTexture2D<half> fullExposureOutput;

void applyPixel(uint2 pixel, bool inspect)
{
    uint w,h; colorOutput.GetDimensions(w,h);
    if(pixel.x>=w || pixel.y>=h) return;
    float3 hdr=max(fullSource[pixel].rgb,0.0);
    float luminance=bartFilmLuminance(hdr);
    float3 y,weights;
    bartFilmSamples(luminance,y,weights);
    float2 uv=(float2(pixel)+.5)/float2(w,h);
    float residual=averagedCoefficients.SampleLevel(linearSampler,uv,0).x;
    float2 low=lowResidual.SampleLevel(linearSampler,uv,0).xy;
    float target=dot(y,weights)+residual-dot(low,weights.xz);
    // No Bart identity shortcut, inverse LUT, or +/-12 EV clamp.
    half gain=half(fusionExposureUE(luminance,target));
    float3 exposed=hdr*exp2(globalEV);
    colorOutput[pixel]=half4(half3(toneOperator(exposed*float(gain))),half(1));
    if(inspect)
    {
        fullExposureOutput[pixel]=gain;
        baseOutput[pixel]=half4(half3(toneOperator(exposed)),half(1));
    }
}
[shader("compute")]
[numthreads(8,8,1)]
void apply_exposure(uint3 tid:SV_DispatchThreadID){applyPixel(tid.xy,true);}
[shader("compute")]
[numthreads(8,8,1)]
void apply_exposure_production(uint3 tid:SV_DispatchThreadID){applyPixel(tid.xy,false);}
