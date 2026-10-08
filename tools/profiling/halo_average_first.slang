// Diagnostic ablation ONLY: retain the old average-HDR-before-nonlinearity
// initialization while keeping the new residual pyramid and full-res apply.
Texture2D<float4> fullSource;
SamplerState linearSampler;
Texture1D<float4> fineLookup;
Texture1D<float4> lowLookup;
float globalEV;
RWTexture2D<float2> compactOutput;
RWTexture2D<float> baseLightnessOutput;
RWTexture2D<float4> lightnessOutput;
[shader("compute")]
[numthreads(4,8,1)]
void initialize_average_first(uint3 tid:SV_DispatchThreadID)
{
    uint w,h; compactOutput.GetDimensions(w,h);
    if(tid.x>=w || tid.y>=h) return;
    float3 rgb=0;
    for(uint y=0;y<4;y++) for(uint x=0;x<4;x++) {
        float2 uv=(float2(tid.xy)+(float2(x,y)+.5)/4.)/float2(w,h);
        rgb+=max(fullSource.SampleLevel(linearSampler,uv,0).rgb,0.);
    }
    float logL=log2(max(dot(rgb/16.,float3(.2126,.7152,.0722)),exp2(-40.)))+globalEV;
    float coord=(saturate((logL+40.)/80.)*2047.+.5)/2048.;
    float3 light=lowLookup.SampleLevel(linearSampler,coord,0).xyz;
    float2 weights=fineLookup.SampleLevel(linearSampler,coord,0).yz;
    compactOutput[tid.xy]=0;
    baseLightnessOutput[tid.xy]=light.z;
    lightnessOutput[tid.xy]=float4(light.xy,weights-.5);
}
