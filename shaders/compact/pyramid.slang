// Matched four-tap residual and weight downsampling.
// Read one residual/weight mip and write the next mip.
Texture2D<float4> coarseLuminance;
Texture2D<float2> layerWeights;
SamplerState linearSampler;
RWTexture2D<float4> lightnessOutput;
RWTexture2D<float2> weightsOutput;

// Schedule pyramid sampling independently of reconstruction kernels.
// Both packed pyramids use the same four bilinear coordinates and arithmetic.
[shader("compute")]
[numthreads(4,16,1)]
void downsample_compact(uint3 tid : SV_DispatchThreadID)
{
    uint w,h,iw,ih;
    lightnessOutput.GetDimensions(w,h);
    coarseLuminance.GetDimensions(iw,ih);
    if(tid.x>=w || tid.y>=h) return;
    float2 uv=(float2(tid.xy)+0.5)/float2(w,h);
    float2 texel=1.0/float2(iw,ih);
    float4 a=coarseLuminance.SampleLevel(linearSampler,uv+texel*float2(-1,-1),0);
    a+=coarseLuminance.SampleLevel(linearSampler,uv+texel*float2(1,-1),0);
    a+=coarseLuminance.SampleLevel(linearSampler,uv+texel*float2(-1,1),0);
    a+=coarseLuminance.SampleLevel(linearSampler,uv+texel*float2(1,1),0);
    float2 b=layerWeights.SampleLevel(linearSampler,uv+texel*float2(-1,-1),0);
    b+=layerWeights.SampleLevel(linearSampler,uv+texel*float2(1,-1),0);
    b+=layerWeights.SampleLevel(linearSampler,uv+texel*float2(-1,1),0);
    b+=layerWeights.SampleLevel(linearSampler,uv+texel*float2(1,1),0);
    weightsOutput[tid.xy]=b*0.25;
    lightnessOutput[tid.xy]=a*0.25;
}

