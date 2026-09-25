// Two-stage 5x5 Guided fit and coefficient averaging.
// Input recovered EV / guide; output averaged slope / intercept.
Texture2D<float2> compactSource;
SamplerState linearSampler;
RWTexture2D<float2> averagedOutput;
#ifndef PACKED_HALF_COEFFICIENTS
#define PACKED_HALF_COEFFICIENTS 1
#endif
// A 16x16 output tile needs a radius-2 coefficient halo, then another
// radius-2 input halo for fitting: 20x20 coefficients and 24x24 input.
static const uint inputHeight=16+4*2;
static const uint coefficientPitch=16+2*2;
static const uint coefficientHeight=16+2*2;

// Precomputed EV/guide input; FP32 moments use one anchor per 16x16 tile.
// Physical row padding changes shared-memory addressing only; filter support
// and floating-point accumulation order use the logical coefficientPitch.
#if PACKED_HALF_COEFFICIENTS
// Round fitted coefficients once, then pack their native half bits into one
// shared word. Unpack to float before the existing FP32 window accumulation.
groupshared uint packedCoefficients[(coefficientPitch+4)*coefficientHeight];
void storeCoefficient(uint i,float2 v) {
    half2 rounded=half2(v);
    packedCoefficients[i]=uint(asuint16(rounded.x)) | (uint(asuint16(rounded.y))<<16);
}
float2 loadCoefficient(uint i) {
    uint packed=packedCoefficients[i];
    return float2(f16tof32(packed&65535),f16tof32(packed>>16));
}
#else
groupshared float2 fusedCoefficients[(coefficientPitch+4)*coefficientHeight];
void storeCoefficient(uint i,float2 v) { fusedCoefficients[i]=v; }
float2 loadCoefficient(uint i) { return fusedCoefficients[i]; }
#endif
static const uint momentPitch=coefficientPitch;
static const uint rowCoefficientPitch=16;
groupshared float4 rowMoments[momentPitch*inputHeight];
// The coefficient-publication barrier ends every moment read before horizontal
// sums are written. Reuse those dead words without another barrier or rounding.
void storeRowCoefficients(uint index, float2 value)
{
    // Preserve the native half conversion. f32tof16 can round differently on
    // D3D12, so pack the converted values' bits instead of converting again.
    half2 rounded = half2(value);
    uint packed = uint(asuint16(rounded.x)) | (uint(asuint16(rounded.y)) << 16);
    rowMoments[index >> 2][index & 3] = asfloat(packed);
}
float2 loadRowCoefficients(uint index)
{
    uint packed = asuint(rowMoments[index >> 2][index & 3]);
    return float2(f16tof32(packed & 65535), f16tof32(packed >> 16));
}

[shader("compute")]
[numthreads(16,16,1)]
void reconstruct_guided(uint3 tid : SV_DispatchThreadID, uint3 localID : SV_GroupThreadID,
                        uint3 groupID : SV_GroupID)
{
    uint w,h;
    averagedOutput.GetDimensions(w,h);
    uint lane=localID.y*16+localID.x;
    int2 origin=int2(groupID.xy*uint2(16,16));
    // Read-only input permits redundant cached loads instead of a shared tile
    // publication barrier. Keep the same tile anchor and FP32 moment order.
    float anchor=compactSource[clamp(origin,int2(0),int2(w-1,h-1))].y;
    // A Gather covers two adjacent rows. Integrate columns 0..3 with four
    // component gathers, then load column 4 directly. Keep the same anchor,
    // five-point support and FP32 accumulation before the existing barrier.
    for(uint task=lane;task<coefficientPitch*(inputHeight/2);task+=16*16) {
        uint col=task%coefficientPitch,row=(task/coefficientPitch)*2;
        float4 first=0,second=0;
        [unroll] for(uint pair=0;pair<2;pair++) {
            float2 uv=(float2(origin)+float2(col+pair*2,row)-float(2*2)+1.)/float2(w,h);
            float4 e=compactSource.GatherRed(linearSampler,uv);
            float4 g=compactSource.GatherGreen(linearSampler,uv)-anchor;
            first+=float4(g.w,e.w,g.w*g.w,g.w*e.w);
            second+=float4(g.x,e.x,g.x*g.x,g.x*e.x);
            if(pair<2) {
                first+=float4(g.z,e.z,g.z*g.z,g.z*e.z);
                second+=float4(g.y,e.y,g.y*g.y,g.y*e.y);
            }
        }
        int2 last=origin+int2(col+4,row)-2*2;
        float2 last0=compactSource[clamp(last,int2(0),int2(w-1,h-1))];
        float2 last1=compactSource[clamp(last+int2(0,1),int2(0),int2(w-1,h-1))];
        float g0=last0.y-anchor,g1=last1.y-anchor;
        first+=float4(g0,last0.x,g0*g0,g0*last0.x);
        second+=float4(g1,last1.x,g1*g1,g1*last1.x);
        rowMoments[row*momentPitch+col]=first;
        rowMoments[(row+1)*momentPitch+col]=second;
    }
    GroupMemoryBarrierWithGroupSync();
    // All six cached rows are in bounds here. Keep the original clamped path
    // for border tiles; no sampling, precision or summation order changes.
    bool interior=all(origin>=int2(2)) && all(origin+int2(16+2,16+2)<=int2(w,h));
    if(interior) {
        for(uint task=lane;task<coefficientPitch*((coefficientHeight+1)/2);task+=16*16) {
            uint col=task%coefficientPitch,row=(task/coefficientPitch)*2;
            float4 cached[6];
            [unroll] for(uint k=0;k<6;k++)cached[k]=rowMoments[(row+k)*momentPitch+col];
            [unroll] for(uint j=0;j<2;j++) {
                float4 moments=0;
                [unroll] for(uint k=0;k<5;k++)moments+=cached[j+k];
                moments/=25.0;
                float variance=max(moments.z-moments.x*moments.x,0.0);
                half covariance=half(moments.w-moments.x*moments.y);
                half denominator=half(variance+0.04);
                half aa=covariance/denominator;
                storeCoefficient((row+j)*(coefficientPitch+4)+col,float2(float(aa),moments.y-float(aa)*(moments.x+anchor)));
            }
        }
    } else
    {
    // Two adjacent vertical windows share six rows. Preserve summation order.
    for(uint task=lane;task<coefficientPitch*((coefficientHeight+1)/2);task+=16*16) {
        uint col=task%coefficientPitch,row=(task/coefficientPitch)*2;
        int2 first=clamp(origin+int2(col,row)-2,int2(0),int2(w-1,h-1));
        int2 start=first-origin+2;
        float4 cached[6];
        [unroll] for(uint k=0;k<6;k++) cached[k]=rowMoments[min(start.y+int(k),int(inputHeight-1))*momentPitch+start.x];
        [unroll] for(uint j=0;j<2;j++) if(row+j<coefficientHeight) {
            int cy=clamp(origin.y+int(row+j)-2,0,int(h-1));
            uint offset=uint(cy-first.y);
            float4 moments=0;
            // Avoid dynamic indexing of a private register array at clamped edges.
            if(offset==0) {
                [unroll] for(uint k=0;k<5;k++) moments+=cached[k];
            } else {
                [unroll] for(uint k=0;k<5;k++) moments+=cached[k+1];
            }
            moments/=25.0;
            float variance=max(moments.z-moments.x*moments.x,0.0);
            half covariance=half(moments.w-moments.x*moments.y);
            half denominator=half(variance+0.04);
            half aa=covariance/denominator;
            storeCoefficient((row+j)*(coefficientPitch+4)+col,float2(float(aa),moments.y-float(aa)*(moments.x+anchor)));
        }
    }
    }
    GroupMemoryBarrierWithGroupSync();
    static const uint coefficientChunks=(16+2-1)/2;
    for(uint chunk=lane;chunk<coefficientChunks*coefficientHeight;chunk+=16*16) {
        uint row=chunk/coefficientChunks,col=(chunk%coefficientChunks)*2;
        float2 values[2+2*2];
        [unroll] for(uint x=0;x<2+2*2;x++)
            values[x]=loadCoefficient(row*(coefficientPitch+4)+min(col+x,coefficientPitch-1));
        float2 sum=0;
        [unroll] for(uint j=0;j<2;j++) {
            sum=0;
            [unroll] for(uint x=0;x<=2*2;x++)sum+=values[j+x];
            if(col+j<16)storeRowCoefficients(row*rowCoefficientPitch+col+j,sum);
        }
    }
    GroupMemoryBarrierWithGroupSync();
    for(uint task=lane;task<16*((16+1)/2);task+=16*16) {
        uint col=task%16,row=(task/16)*2;
        float2 cached[6];
        [unroll] for(uint k=0;k<6;k++) cached[k]=loadRowCoefficients(min(row+k,coefficientHeight-1)*rowCoefficientPitch+col);
        [unroll] for(uint j=0;j<2;j++) {
            uint2 pixel=uint2(origin)+uint2(col,row+j);
            if(row+j<16 && pixel.x<w && pixel.y<h) {
                float2 sum=0;
                [unroll] for(uint k=0;k<5;k++)sum+=cached[j+k];
                averagedOutput[pixel]=sum/25.0;
            }
        }
    }
    return;
}

