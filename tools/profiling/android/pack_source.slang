// Host-side input preparation only, outside all phone timestamp intervals.
Texture2D<float4> inputTexture;
RWTexture2D<float4> outputTexture;
[shader("compute")]
[numthreads(8, 8, 1)]
void pack_source(uint3 tid : SV_DispatchThreadID)
{
    uint w, h;
    outputTexture.GetDimensions(w, h);
    if(tid.x>=w || tid.y>=h) return;
    outputTexture[tid.xy] = inputTexture[tid.xy];
}
