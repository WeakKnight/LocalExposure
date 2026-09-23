float4 zParameters; // contrast, shoulder, b, c
float zMaxInput;
float zMaxLightness;
Texture1D<float> inverseLut; // log2(linear luminance), monotonically increasing
SamplerState inverseSampler;
uint inverseSize;
float inverseWarpEpsilon;
float inverseWarpSpan;

float fusionLightness(float luminance)
{
    if (luminance >= zMaxInput) return zMaxLightness;
    float z = pow(clamp(luminance, 0.0, zMaxInput), zParameters.x);
    float y = z / (zParameters.z * pow(z, zParameters.y) + zParameters.w);
    return min(sqrt(max(y, 0.0)), zMaxLightness);
}

float inverseFusionLightness(float lightness)
{
    if (lightness <= 0.0) return 0.0;
    if (lightness >= zMaxLightness) return zMaxInput;
    float t = saturate(lightness / zMaxLightness);
    // Logit spacing resolves both dark values and the near-white shoulder.
    float u = 0.5 + log2((t + inverseWarpEpsilon) / (1.0 - t + inverseWarpEpsilon)) / (2.0 * inverseWarpSpan);
    float coord = (saturate(u) * float(inverseSize - 1) + 0.5) / float(inverseSize);
    // Half storage can round log2(65535) to 16; keep the decoded endpoint in range.
    return min(exp2(inverseLut.SampleLevel(inverseSampler, coord, 0)), zMaxInput);
}
