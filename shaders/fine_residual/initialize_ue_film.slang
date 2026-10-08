#include "../ue_film_curve.slang"
Texture2D<float4> fullSource;
SamplerState linearSampler;
RWTexture2D<float2> compactOutput;
RWTexture2D<float> baseLightnessOutput;
RWTexture2D<float4> lightnessOutput;

[shader("compute")]
[numthreads(4,8,1)]
void reduce_setup_gather(uint3 tid:SV_DispatchThreadID)
{
    uint w,h; compactOutput.GetDimensions(w,h);
    if(tid.x>=w || tid.y>=h) return;
    float3 light=0; float2 weights=0;
    for(uint y=0;y<2;y++) for(uint x=0;x<2;x++)
    {
        float2 uv=(float2(tid.xy)+(float2(x,y)+.5)/2.)/float2(w,h);
        float3 samples,ws;
        bartFilmSamples(bartFilmLuminance(fullSource.SampleLevel(linearSampler,uv,0).rgb),samples,ws);
        light+=float3(samples.x-samples.y,samples.z-samples.y,samples.y);
        weights+=ws.xz;
    }
    light*=.25; weights*=.25;
    compactOutput[tid.xy]=0;
    baseLightnessOutput[tid.xy]=light.z;
    lightnessOutput[tid.xy]=float4(light.xy,weights-.5);
}
