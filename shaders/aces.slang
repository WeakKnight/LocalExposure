float3 acesFilmic(float3 x)
{
    x = clamp(x, 0.0, 1e10);
    return saturate((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14));
}
