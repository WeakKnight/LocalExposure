// Four bilinear HDR samples; evaluate exposures before averaging.
// Outputs: packed lightness residuals/weights and FP32 baseline.
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
void reduce_setup_gather(uint3 tid:SV_DispatchThreadID){
 uint w,h;compactOutput.GetDimensions(w,h);if(tid.x>=w||tid.y>=h)return;
 float3 light=0;float2 weights=0;
 for(uint y=0;y<2;y++)for(uint x=0;x<2;x++){
  float2 uv=(float2(tid.xy)+(float2(x,y)+.5)/2.)/float2(w,h);
  float3 rgb=max(fullSource.SampleLevel(linearSampler,uv,0).rgb,0.);
  float logL=log2(max(dot(rgb,float3(.2126,.7152,.0722)),exp2(-40.)))+globalEV;
  float coord=(saturate((logL+40.)/80.)*2047.+.5)/2048.;
  light+=lowLookup.SampleLevel(linearSampler,coord,0).xyz;
  weights+=fineLookup.SampleLevel(linearSampler,coord,0).yz;
 }
 light/=4.;weights/=4.;
 compactOutput[tid.xy]=0; baseLightnessOutput[tid.xy]=light.z;
 lightnessOutput[tid.xy]=float4(light.xy,weights-.5);
}

[shader("compute")]
[numthreads(4,8,1)]
void reduce_setup(uint3 tid:SV_DispatchThreadID){reduce_setup_gather(tid);}
