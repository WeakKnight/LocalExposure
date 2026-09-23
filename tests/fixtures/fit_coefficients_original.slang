// Frozen original guided fit.
Texture2D<float4> reducedSource;
Texture2D<half> lowExposure;
RWTexture2D<float2> coefficientOutput;

// Fast guided filter: fit EV = a * log-luminance + b in a 5x5 low-res window.
// Guide was averaged in log space separately from linear HDR downsampling.
[shader("compute")]
[numthreads(8, 8, 1)]
void fit_coefficients(uint3 tid : SV_DispatchThreadID)
{
    uint w, h;
    coefficientOutput.GetDimensions(w, h);
    if (tid.x >= w || tid.y >= h) return;
    float center = reducedSource[tid.xy].a;
    // Only per-sample centered values/products use half. Accumulate all 25
    // samples and solve covariance/variance in float to avoid cancellation.
    // Form the cancellation-sensitive differences in float before narrowing.
    // Intercept construction, coefficient storage and final a*guide+b stay float.
    float meanG = 0, meanE = 0, meanGG = 0, meanGE = 0;
    for (int y = -2; y <= 2; ++y)
        for (int x = -2; x <= 2; ++x)
        {
            int2 p = clamp(int2(tid.xy) + int2(x, y), int2(0), int2(w-1, h-1));
            // Subtract in float before narrowing: small guide differences
            // would disappear if the two absolute log values were half.
            half g = half(reducedSource[p].a - center);
            half e = half(log2(max(lowExposure[p], 1e-20)));
            meanG += g; meanE += e; meanGG += float(g*g); meanGE += float(g*e);
        }
    meanG /= 25; meanE /= 25; meanGG /= 25; meanGE /= 25;
    float variance = max(meanGG - meanG*meanG, 0.0);
    // Regularization keeps the denominator >= 0.04; the centered covariance
    // and regularized denominator can be narrowed before half division.
    half covariance = half(meanGE - meanG*meanE);
    half denominator = half(variance + 0.04); // epsilon: EV^2
    half a = covariance / denominator;
    coefficientOutput[tid.xy] = float2(float(a), meanE - float(a)*(meanG + center));
}

