// Matched four-tap residual and weight downsampling.
// xy holds residuals, zw holds weights - 0.5; linear filtering handles both.
// Mips 0-2 use RGBA16F; the smaller coarse mips use RGBA32F.
Texture2D<float4> coarseLuminance;
SamplerState linearSampler;
RWTexture2D<float4> lightnessOutput;

// Schedule pyramid sampling independently of reconstruction kernels.
// One sample fetches both residuals and weights at each bilinear coordinate.
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
    lightnessOutput[tid.xy]=a*0.25;
}

