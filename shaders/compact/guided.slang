// Full 5x5 Guided fitting and separable 5x5 coefficient averaging.
// Each 8x8 workgroup produces a 16x16 output tile. Fitting includes a
// two-pixel coefficient halo; input samples clamp at the image boundary.
// Direct statistics avoid the row-moment buffer and its publication barrier.
Texture2D<float2> compactSource;
RWTexture2D<float2> averagedOutput;
#ifndef PACKED_HALF_COEFFICIENTS
#define PACKED_HALF_COEFFICIENTS 1
#endif
#if PACKED_HALF_COEFFICIENTS
groupshared uint coefficients[20*20];
#else
groupshared float2 coefficients[20*20];
#endif
groupshared uint rowSums[16*20];
uint pack(half2 v) {return uint(asuint16(v.x))|(uint(asuint16(v.y))<<16);}
float2 unpack(uint v) {return float2(f16tof32(v&65535),f16tof32(v>>16));}
void storeCoefficient(uint index,float2 value) {
#if PACKED_HALF_COEFFICIENTS
    coefficients[index]=pack(half2(value));
#else
    coefficients[index]=value;
#endif
}
float2 loadCoefficient(uint index) {
#if PACKED_HALF_COEFFICIENTS
    return unpack(coefficients[index]);
#else
    return coefficients[index];
#endif
}
[shader("compute")]
[numthreads(8,8,1)]
void reconstruct_guided(uint3 local:SV_GroupThreadID,uint3 group:SV_GroupID) {
    uint w,h;averagedOutput.GetDimensions(w,h);
    uint lane=local.y*8+local.x;
    int2 origin=int2(group.xy*16);
    // Keep statistics in float; centering the guide limits cancellation.
    float anchor=compactSource[clamp(origin,int2(0),int2(w-1,h-1))].y;
    for(uint task=lane;task<20*20;task+=64) {
        int2 center=clamp(origin+int2(task%20,task/20)-2,int2(0),int2(w-1,h-1));
        float4 sum=0;
        [unroll] for(int y=-2;y<=2;y++) {
            float4 row=0;
            [unroll] for(int x=-2;x<=2;x++) {
                float2 v=compactSource[clamp(center+int2(x,y),int2(0),int2(w-1,h-1))];
                float g=v.y-anchor;
                row+=float4(g,v.x,g*g,g*v.x);
            }
            sum+=row;
        }
        float4 m=sum/25.;
        float variance=max(m.z-m.x*m.x,0.);
        half covariance=half(m.w-m.x*m.y);
        half denominator=half(variance+.04);
        half a=covariance/denominator;
        storeCoefficient(task,float2(float(a),m.y-float(a)*(m.x+anchor)));
    }
    GroupMemoryBarrierWithGroupSync();
    // Preserve the reference's half rounding between horizontal and vertical
    // coefficient averaging. This is distinct from fitted-coefficient storage.
    for(uint task=lane;task<16*20;task+=64) {
        uint x=task%16,y=task/16;
        float2 sum=0;
        [unroll] for(uint k=0;k<5;k++)sum+=loadCoefficient(y*20+x+k);
        rowSums[task]=pack(half2(sum));
    }
    GroupMemoryBarrierWithGroupSync();
    for(uint task=lane;task<256;task+=64) {
        uint2 point=uint2(task%16,task/16);
        uint2 pixel=uint2(origin)+point;
        if(pixel.x>=w || pixel.y>=h)continue;
        float2 sum=0;
        [unroll] for(uint k=0;k<5;k++)sum+=unpack(rowSums[(point.y+k)*16+point.x]);
        averagedOutput[pixel]=sum/25.;
    }
}
