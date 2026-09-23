// Frozen pre-tile implementation for exact GPU regression.
Texture2D<float2> coefficients;
RWTexture2D<float2> averagedOutput;

[shader("compute")]
[numthreads(8, 8, 1)]
void average_coefficients(uint3 tid : SV_DispatchThreadID)
{
    uint w, h;
    averagedOutput.GetDimensions(w, h);
    if (tid.x >= w || tid.y >= h) return;
    float2 sum = 0;
    for (int y = -2; y <= 2; ++y)
        for (int x = -2; x <= 2; ++x)
            sum += coefficients[clamp(int2(tid.xy) + int2(x, y), int2(0), int2(w-1, h-1))];
    averagedOutput[tid.xy] = sum / 25.0;
}

