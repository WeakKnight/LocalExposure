// Offscreen render-target equivalents of the production backbuffer passes.
// Reuse core exposure and tone-operator math; sRGB conversion is attachment hardware.
#include "guided.slang"
#ifndef WORK_X
#define WORK_X 8
#endif
#ifndef WORK_Y
#define WORK_Y 8
#endif

[shader("vertex")]
float4 fullscreen_vertex(uint id : SV_VertexID) : SV_Position
{
    return float4(id == 2 ? 3.0 : -1.0, id == 1 ? 3.0 : -1.0, 0.0, 1.0);
}

[shader("fragment")]
float4 apply_fragment(float4 position : SV_Position) : SV_Target
{
    uint w, h;
    fullSource.GetDimensions(w,h);
    uint2 pixel=uint2(position.xy);
    float3 hdr=max(fullSource[pixel].rgb,0.0);
    half multiplier=exposureMultiplier(pixel,uint2(w,h),hdr);
    float3 color=hdr*exp2(globalEV);
    return float4(half3(toneOperator(color*float(multiplier))),1.0);
}

[shader("fragment")]
float4 baseline_fragment(float4 position : SV_Position) : SV_Target
{
    float3 color=max(fullSource[uint2(position.xy)].rgb,0.0)*exp2(globalEV);
    return float4(half3(toneOperator(color)),1.0);
}

[shader("fragment")]
float4 reference_fragment(float4 position : SV_Position) : SV_Target
{
    return fullSource[uint2(position.xy)];
}


// Storage writes use a compatible UNORM view of the actual sRGB image.
// Conversion is explicit because Vulkan storage stores do not encode sRGB.
RWTexture2D<float4> srgbOutput;
float3 encodeSRGB(float3 linear)
{
    return select(linear<=0.0031308,linear*12.92,1.055*pow(max(linear,0.0),1.0/2.4)-0.055);
}
[shader("compute")]
[numthreads(WORK_X,WORK_Y,1)]
void apply_srgb_compute(uint3 tid : SV_DispatchThreadID)
{
    uint w,h;
    srgbOutput.GetDimensions(w,h);
    if(tid.x>=w || tid.y>=h) return;
    float3 hdr=max(fullSource[tid.xy].rgb,0.0);
    half multiplier=exposureMultiplier(tid.xy,uint2(w,h),hdr);
    float3 color=hdr*exp2(globalEV);
    float3 linear=float3(half3(toneOperator(color*float(multiplier))));
    srgbOutput[tid.xy]=float4(encodeSRGB(linear),1.0);
}
[shader("compute")]
[numthreads(WORK_X,WORK_Y,1)]
void baseline_srgb_compute(uint3 tid : SV_DispatchThreadID)
{
    uint w,h;
    srgbOutput.GetDimensions(w,h);
    if(tid.x>=w || tid.y>=h) return;
    float3 color=max(fullSource[tid.xy].rgb,0.0)*exp2(globalEV);
    float3 linear=float3(half3(toneOperator(color)));
    srgbOutput[tid.xy]=float4(encodeSRGB(linear),1.0);
}
