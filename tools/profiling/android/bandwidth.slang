// Native streaming bandwidth diagnostics, independent of Fusion arithmetic.
uint elementCount;
RWStructuredBuffer<uint4> sourceData;
RWStructuredBuffer<uint4> destinationData;

uint hashWord(uint x)
{
    x ^= x >> 16; x *= 0x7feb352du;
    x ^= x >> 15; x *= 0x846ca68bu;
    return x ^ (x >> 16);
}

[shader("compute")]
[numthreads(256, 1, 1)]
void initialize(uint3 tid : SV_DispatchThreadID)
{
    if (tid.x >= elementCount) return;
    sourceData[tid.x] = uint4(hashWord(4*tid.x), hashWord(4*tid.x+1),
                            hashWord(4*tid.x+2), hashWord(4*tid.x+3));
}

[shader("compute")]
[numthreads(256, 1, 1)]
void stream_copy(uint3 tid : SV_DispatchThreadID)
{
    if (tid.x >= elementCount) return;
    destinationData[tid.x] = sourceData[tid.x];
}
