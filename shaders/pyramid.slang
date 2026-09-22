Texture2D<float4> inputTexture;
RWTexture2D<float4> outputTexture;
SamplerState linearSampler;

// UE Fusion's High downsample: four bilinear taps, offsets in INPUT texels.
// With aligned 2:1 dimensions, this is a 4x4 box footprint (not Gaussian).
[shader("compute")]
[numthreads(8, 8, 1)]
void downsample(uint3 tid : SV_DispatchThreadID)
{
    uint width, height, inputWidth, inputHeight;
    outputTexture.GetDimensions(width, height);
    inputTexture.GetDimensions(inputWidth, inputHeight);
    if (tid.x >= width || tid.y >= height) return;
    float2 uv = (float2(tid.xy) + 0.5) / float2(width, height);
    float2 texel = 1.0 / float2(inputWidth, inputHeight);
    float4 value = inputTexture.SampleLevel(linearSampler, uv + texel * float2(-1, -1), 0);
    value += inputTexture.SampleLevel(linearSampler, uv + texel * float2(1, -1), 0);
    value += inputTexture.SampleLevel(linearSampler, uv + texel * float2(-1, 1), 0);
    value += inputTexture.SampleLevel(linearSampler, uv + texel * float2(1, 1), 0);
    outputTexture[tid.xy] = value * 0.25;
}

#include "lut_proxy.slang"
Texture2D<float4> hdrSource;
RWTexture2D<float4> baseOutput;
float globalEV;
float highlightEV;
float shadowEV;
RWTexture2D<float4> luminanceOutput;
RWTexture2D<float4> weightOutput;
float sigma;

float lightness(float3 color)
{
    return sqrt(max(dot(color, float3(0.2126, 0.7152, 0.0722)), 0.0));
}

[shader("compute")]
[numthreads(8, 8, 1)]
void setup_weights(uint3 tid : SV_DispatchThreadID)
{
    uint width, height;
    weightOutput.GetDimensions(width, height);
    if (tid.x >= width || tid.y >= height) return;
    // Channels encode exposures, not color: R=darker, G=base, B=brighter.
    float3 hdr = max(hdrSource[tid.xy].rgb, 0.0);
    float3 darker = proxyToneOperator(hdr * exp2(globalEV - highlightEV));
    float3 base = proxyToneOperator(hdr * exp2(globalEV));
    float3 brighter = proxyToneOperator(hdr * exp2(globalEV + shadowEV));
    baseOutput[tid.xy] = float4(toneOperator(hdr * exp2(globalEV)), 1.0);
    float3 y = float3(lightness(darker), lightness(base), lightness(brighter));
    float3 distance = y - 0.5;
    float3 logWeight = -distance * distance / (2.0 * sigma * sigma);
    // Equivalent normalized Gaussian; subtract maximum to avoid underflow
    // when all exposures are far from the target and sigma is small.
    // UE Fusion uses base-2 exponential with Sigma=0.2 (not natural exp).
    float3 weights = exp2(logWeight - max(logWeight.x, max(logWeight.y, logWeight.z)));
    weights /= weights.x + weights.y + weights.z;
    luminanceOutput[tid.xy] = float4(y, 1.0);
    weightOutput[tid.xy] = float4(weights, 1.0);
}
