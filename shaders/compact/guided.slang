// Full 5x5 Guided fitting and separable 5x5 coefficient averaging.
// Each 64x1 workgroup produces a 16x16 output tile. Fitting includes a
// two-pixel coefficient halo; input samples clamp at the image boundary.
// Four vertically adjacent fits share eight input rows in registers.
// Keep each five-row sum in its original order; no sliding-sum cancellation.
// This avoids a shared row-moment buffer and its publication barrier.
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
[numthreads(64,1,1)]
void reconstruct_guided(uint3 local:SV_GroupThreadID,uint3 group:SV_GroupID) {
    uint w,h;averagedOutput.GetDimensions(w,h);
    uint lane=local.y*8+local.x;
    int2 origin=int2(group.xy*16);
    // FP32 raw moments avoid a subtraction per input in the optimized path.
    // This changes rounding; final-image checks cover near-constant HDR guides.
    // The independent FP32 coefficient control retains centered statistics.
#if PACKED_HALF_COEFFICIENTS
    float anchor=0.0;
#else
    float anchor=compactSource[clamp(origin,int2(0),int2(w-1,h-1))].y;
#endif
    // 20 columns, five batches of four coefficients, including the halo.
    for(uint task=lane;task<20*5;task+=64) {
        uint col=task%20,row=(task/20)*4;
        int2 center=clamp(origin+int2(col,row)-2,int2(0),int2(w-1,h-1));
        float4 rows[8];
        [unroll] for(int y=0;y<8;y++) {
            float4 sum=0;
            [unroll] for(int x=-2;x<=2;x++) {
                float2 v=compactSource[clamp(center+int2(x,y-2),int2(0),int2(w-1,h-1))];
                float g=v.y-anchor;
                sum+=float4(g,v.x,g*g,g*v.x);
            }
            rows[y]=sum;
        }
        // Interior batches use fixed row windows. Clamped border coefficients
        // can share a center; explicit cases avoid dynamic indexing of the
        // private array, preserving register storage.
        [unroll] for(uint j=0;j<4;j++) {
            uint offset=uint(clamp(origin.y+int(row+j)-2,0,int(h)-1)-center.y);
            float4 sum=0;
            if(origin.y+int(row)-2>=0 && origin.y+int(row)+1<int(h)) { [unroll] for(uint k=0;k<5;k++)sum+=rows[k+j]; }
            else if(offset==0) { [unroll] for(uint k=0;k<5;k++)sum+=rows[k+0]; }
            else if(offset==1) { [unroll] for(uint k=0;k<5;k++)sum+=rows[k+1]; }
            else if(offset==2) { [unroll] for(uint k=0;k<5;k++)sum+=rows[k+2]; }
            else if(offset==3) { [unroll] for(uint k=0;k<5;k++)sum+=rows[k+3]; }
            float4 m=sum/25.;
            float variance=max(m.z-m.x*m.x,0.);
            half covariance=half(m.w-m.x*m.y);
            half denominator=half(variance+.04);
            half a=covariance/denominator;
            storeCoefficient((row+j)*20+col,float2(float(a),m.y-float(a)*(m.x+anchor)));
        }
    }
    GroupMemoryBarrierWithGroupSync();
    // Preserve the reference's half rounding between horizontal and vertical
    // coefficient averaging. This is distinct from fitted-coefficient storage.
    // Four adjacent averages share eight coefficients; preserve sum order.
    for(uint task=lane;task<4*20;task+=64) {
        uint x=(task%4)*4,y=task/4;
        float2 values[8];
        [unroll] for(uint k=0;k<8;k++) values[k]=loadCoefficient(y*20+x+k);
        [unroll] for(uint j=0;j<4;j++) {
            float2 sum=0;
            [unroll] for(uint k=0;k<5;k++)sum+=values[k+j];
            rowSums[y*16+x+j]=pack(half2(sum));
        }
    }
    GroupMemoryBarrierWithGroupSync();
    // Repeat the reuse vertically after publishing the rounded horizontal sums.
    uint x=lane%16,y=(lane/16)*4;
    float2 values[8];
    [unroll] for(uint k=0;k<8;k++)values[k]=unpack(rowSums[(y+k)*16+x]);
    [unroll] for(uint j=0;j<4;j++) {
        uint2 pixel=uint2(origin)+uint2(x,y+j);
        if(pixel.x>=w || pixel.y>=h)continue;
        float2 sum=0;
        [unroll] for(uint k=0;k<5;k++)sum+=values[k+j];
        averagedOutput[pixel]=sum/25.;
    }
}
