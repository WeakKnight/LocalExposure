// Small pyramid tail reduced and reconstructed within one workgroup.
// Read packed xy residuals / zw centered weights; write reconstructed residual.
Texture2D<float4> fineLuminance;
RWTexture2D<float> reconstructionOutput;

// The host selects a base of at most 16x8. The backing arrays retain the
// original 32x16 capacity. This stage is approximate:
// shared-memory bilinear interpolation replaces hardware texture interpolation.
// Separate components avoid the unused zw channels and four-float LDS stride.
groupshared float tailResidual0[683];
groupshared float tailResidual1[683];
float4 loadTailLightness(uint i) { return float4(tailResidual0[i],tailResidual1[i],0,0); }
void storeTailLightness(uint i,float4 value) { tailResidual0[i]=value.x;tailResidual1[i]=value.y; }
groupshared float2 tailWeights[683];
groupshared float tailResult[683];
uint tailLevels;
struct TailSample { float4 lightness; float2 weights; float reconstruction; };
TailSample sampleTail(uint offset,uint2 size,float2 uv,bool readResult=true)
{
    float2 pos=uv*float2(size)-0.5;
    int2 base=int2(floor(pos));float2 f=pos-float2(base);
    int2 p0=clamp(base,int2(0),int2(size)-1),p1=clamp(base+1,int2(0),int2(size)-1);
    uint a=offset+p0.y*size.x+p0.x,b=offset+p0.y*size.x+p1.x;
    uint c=offset+p1.y*size.x+p0.x,d=offset+p1.y*size.x+p1.x;
    TailSample value;
    value.lightness=lerp(lerp(loadTailLightness(a),loadTailLightness(b),f.x),lerp(loadTailLightness(c),loadTailLightness(d),f.x),f.y);
    value.weights=lerp(lerp(tailWeights[a],tailWeights[b],f.x),lerp(tailWeights[c],tailWeights[d],f.x),f.y);
    value.reconstruction=readResult ? lerp(lerp(tailResult[a],tailResult[b],f.x),lerp(tailResult[c],tailResult[d],f.x),f.y) : 0.0;
    return value;
}
[shader("compute")]
[numthreads(16,8,1)]
void tail_reconstruct(uint3 local : SV_GroupThreadID)
{
    uint w,h;reconstructionOutput.GetDimensions(w,h);
    uint lane=local.y*16+local.x;
    uint levelOffset=0;uint2 currentSize=uint2(w,h);
    for(uint y=local.y;y<h;y+=8)for(uint x=local.x;x<w;x+=16) {
        uint i=y*w+x;uint2 p=uint2(x,y);
        storeTailLightness(i,fineLuminance[p]);tailWeights[i]=fineLuminance[p].zw+.5;
    }
    GroupMemoryBarrierWithGroupSync();
    for(uint m=1;m<tailLevels;m++) {
        uint2 previous=currentSize;uint previousOffset=levelOffset;
        currentSize=max(previous/2,uint2(1));levelOffset+=previous.x*previous.y;
        uint2 size=currentSize;uint outputOffset=levelOffset;
        for(uint y=local.y;y<size.y;y+=8)for(uint x=local.x;x<size.x;x+=16) {
            uint i=y*size.x+x;uint2 pixel=uint2(x,y);
            float2 uv=(float2(pixel)+.5)/float2(size),texel=1.0/float2(previous);
            // Reconstruction starts only after the downsample pyramid is complete.
            TailSample a=sampleTail(previousOffset,previous,uv+texel*float2(-1,-1),false);
            TailSample b=sampleTail(previousOffset,previous,uv+texel*float2(1,-1),false);
            TailSample c=sampleTail(previousOffset,previous,uv+texel*float2(-1,1),false);
            TailSample d=sampleTail(previousOffset,previous,uv+texel*float2(1,1),false);
            uint index=outputOffset+i;
            // Preserve the retained pyramid's per-level RG16F / RG16_UNORM storage.
            float2 residual=(((a.lightness.xy+b.lightness.xy)+c.lightness.xy)+d.lightness.xy)*.25;
            storeTailLightness(index,float4(float2(half2(residual)),0,0));
            float2 weights=(((a.weights+b.weights)+c.weights)+d.weights)*.25;
            tailWeights[index]=floor(saturate(weights)*65535.0+0.5)/65535.0;
            // The last downsample already owns the coarsest texel. Evaluate its
            // weighted base here using the stored (rounded) values, then publish
            // it with the existing barrier instead of a separate reverse step.
            if(m==tailLevels-1) {
                float2 baseWeights=tailWeights[index];
                float2 contribution=loadTailLightness(index).xy*baseWeights;
                tailResult[index]=contribution.x+contribution.y;
            }
        }
        GroupMemoryBarrierWithGroupSync();
    }
    int firstReverse=int(tailLevels)-1;
    if(firstReverse>0) {
        firstReverse--;
        uint2 size=max(uint2(w,h)>>firstReverse,uint2(1));
        levelOffset-=size.x*size.y;
    }
    for(int m=firstReverse;m>=0;m--) {
        uint2 size=max(uint2(w,h)>>m,uint2(1));uint outputOffset=levelOffset;
        uint2 coarseSize=max(size/2,uint2(1));uint coarseOffset=levelOffset+size.x*size.y;
        bool coarsest=m==int(tailLevels)-1;
        for(uint y=local.y;y<size.y;y+=8)for(uint x=local.x;x<size.x;x+=16) {
            uint i=y*size.x+x;uint2 pixel=uint2(x,y);
            uint index=outputOffset+i;float4 fine=loadTailLightness(index);float3 detail=fine.rgb;float previous=0;
            if(!coarsest){TailSample coarse=sampleTail(coarseOffset,coarseSize,(float2(pixel)+.5)/float2(size));detail-=coarse.lightness.rgb;previous=coarse.reconstruction;}
            float2 weights=tailWeights[index];
            float2 contribution=detail.xy*weights;
            float value=(contribution.x+contribution.y)+previous;
            if(m==0)reconstructionOutput[pixel]=value;
            else tailResult[index]=value;
        }
        if(m>0)GroupMemoryBarrierWithGroupSync();
        if(m>0){uint2 finer=max(uint2(w,h)>>(m-1),uint2(1));levelOffset-=finer.x*finer.y;}
    }
}
