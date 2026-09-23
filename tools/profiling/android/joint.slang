// Experimental alternative upsampler; isolated from the retained guided path.
#include "present.slang"
#ifndef JOINT_SIGMA
#define JOINT_SIGMA 0.5
#endif
Texture2D<float2> jointGuideExposure;
half jointMultiplier(uint2 pixel,uint2 size,float3 hdr)
{
    uint w,h;jointGuideExposure.GetDimensions(w,h);
    float2 p=(float2(pixel)+.5)/float2(size)*float2(w,h)-.5;
    int2 base=int2(floor(p));float2 f=p-float2(base);
    int2 a=clamp(base,int2(0),int2(w-1,h-1)),b=clamp(base+1,int2(0),int2(w-1,h-1));
    float2 v0=jointGuideExposure[a],v1=jointGuideExposure[int2(b.x,a.y)];
    float2 v2=jointGuideExposure[int2(a.x,b.y)],v3=jointGuideExposure[b];
    float4 spatial=float4((1-f.x)*(1-f.y),f.x*(1-f.y),(1-f.x)*f.y,f.x*f.y);
    float4 difference=float4(v0.y,v1.y,v2.y,v3.y)-logGuide(hdr);
    float4 logWeight=select(spatial>0,-difference*difference/(JOINT_SIGMA*JOINT_SIGMA),-1e30);
    float largest=max(max(logWeight.x,logWeight.y),max(logWeight.z,logWeight.w));
    float4 weights=spatial*exp2(logWeight-largest);
    float ev=dot(weights,float4(v0.x,v1.x,v2.x,v3.x))/max(dot(weights,float4(1)),1e-20);
    return half(exp2(clamp(ev,-12.0,12.0)));
}
[shader("compute")]
[numthreads(8,8,1)]
void apply_joint_compute(uint3 tid : SV_DispatchThreadID)
{
    uint w,h;srgbOutput.GetDimensions(w,h);if(tid.x>=w || tid.y>=h)return;
    float3 hdr=max(fullSource[tid.xy].rgb,0.0);
    float3 color=hdr*exp2(globalEV)*float(jointMultiplier(tid.xy,uint2(w,h),hdr));
    srgbOutput[tid.xy]=float4(encodeSRGB(float3(half3(toneOperator(color)))),1.0);
}
[shader("compute")]
[numthreads(8,8,1)]
void apply_joint_linear(uint3 tid : SV_DispatchThreadID)
{
    uint w,h;colorOutput.GetDimensions(w,h);if(tid.x>=w || tid.y>=h)return;
    float3 hdr=max(fullSource[tid.xy].rgb,0.0);
    float3 color=hdr*exp2(globalEV)*float(jointMultiplier(tid.xy,uint2(w,h),hdr));
    colorOutput[tid.xy]=half4(half3(toneOperator(color)),half(1));
}
