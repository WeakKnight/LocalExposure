Texture2D<float> inputTexture;
RWTexture2D<uint> outputTexture;
[shader("compute")]
[numthreads(8, 8, 1)]
void pack_probe(uint3 tid : SV_DispatchThreadID)
{
    outputTexture[tid.xy] = uint(asuint16(half(inputTexture[tid.xy])));
}
