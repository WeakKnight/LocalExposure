// Standalone equations audited against UE 5.8's PostProcessHistogramCommon.ush
// and the neutral-axis response of TonemapCommon.ush. No fitted inverse LUT.
float3 luminanceWeights;
float histogramMin;
float histogramMax;
float globalEV;
float preExposure;
float highlightContrast;
float shadowContrast;
float detailStrength;
float blurredBlend;
float middleGreyBias;
float greyMultiplier;
float highlightThreshold;
float shadowThreshold;
float highlightThresholdStrength;
float shadowThresholdStrength;
float filmSlope;
float filmToe;
float filmShoulder;
float filmBlackClip;
float filmWhiteClip;

float eyeLuminance(float3 rgb)
{
    return max(dot(rgb, luminanceWeights), exp2(histogramMin));
}

float histogramPosition(float logLum)
{
    return (logLum - histogramMin) / (histogramMax - histogramMin);
}

// Neutral RGB has no chroma, glow or desaturation contribution. This is the
// scalar specialization used by ExposureFusionTonemap, not RGB FilmToneMap.
float filmNeutral(float luminance)
{
    float toeScale = 1.0 + filmBlackClip - filmToe;
    float shoulderScale = 1.0 + filmWhiteClip - filmShoulder;
    float toeMatch;
    if (filmToe > 0.8)
        toeMatch = (1.0 - filmToe - 0.18) / filmSlope + log10(0.18);
    else
    {
        float bt = (0.18 + filmBlackClip) / toeScale - 1.0;
        toeMatch = log10(0.18) - 0.5 * log((1.0 + bt) / (1.0 - bt)) * toeScale / filmSlope;
    }
    float straightMatch = (1.0 - filmToe) / filmSlope - toeMatch;
    float shoulderMatch = filmShoulder / filmSlope - straightMatch;
    float logColor = log10(luminance);
    float straight = filmSlope * (logColor + straightMatch);
    float toe = -filmBlackClip + 2.0 * toeScale /
        (1.0 + exp(-2.0 * filmSlope / toeScale * (logColor - toeMatch)));
    float shoulder = 1.0 + filmWhiteClip - 2.0 * shoulderScale /
        (1.0 + exp(2.0 * filmSlope / shoulderScale * (logColor - shoulderMatch)));
    toe = logColor < toeMatch ? toe : straight;
    shoulder = logColor > shoulderMatch ? shoulder : straight;
    float t = saturate((logColor - toeMatch) / (shoulderMatch - toeMatch));
    if (shoulderMatch < toeMatch) t = 1.0 - t;
    t = (3.0 - 2.0 * t) * t * t;
    return max(0.0, lerp(toe, shoulder, t));
}

float fusionLightnessUE(float luminance)
{
    return sqrt(filmNeutral(luminance));
}

float fusionExposureUE(float luminance, float fused)
{
    // UE's inverse has fixed constants even when the forward film settings
    // change. Preserve this approximation and the upper-only result clamp.
    float y = saturate(min(fused, 1.0) * min(fused, 1.0));
    float toe = 0.374816 * pow(0.9 / min(y, 0.8) - 1.0, -0.588729);
    float shoulder = 0.227986 * pow(1.56 / (1.04 - y) - 1.0, 1.02046);
    float t = saturate((y - 0.35) / 0.1);
    t = (3.0 - 2.0 * t) * t * t;
    return max(0.0, lerp(toe, shoulder, t)) / luminance;
}

float bilateralExposureUE(float logLum, float base)
{
    float middle = log2(0.18 * greyMultiplier) + middleGreyBias;
    float detail = logLum - base;
    float centered = base - middle;
    bool highlight = centered > 0.0;
    float threshold = highlight ? highlightThreshold : shadowThreshold;
    float strength = highlight ? highlightThresholdStrength : shadowThresholdStrength;
    float m = highlight ? max(0.0, centered - threshold) : min(0.0, centered + threshold);
    // Strength 1 has an infinite ramp width in UE; use its finite-limit value.
    float t = strength >= 1.0 ? 0.0 : smoothstep(threshold, threshold + 1.0 / (1.0 - strength), abs(centered));
    float offset = (centered - m) * (1.0 - t);
    float contrast = highlight ? highlightContrast : shadowContrast;
    float result = middle + offset + (centered - offset) * contrast + detail * detailStrength;
    return exp2(result - logLum);
}
