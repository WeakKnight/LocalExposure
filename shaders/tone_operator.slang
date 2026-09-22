#include "aces.slang"

// Shared black-box adapter: calibration and rendering must call the same operator.
// Return display-linear Rec.709 RGB, before sRGB encoding.
float3 toneOperator(float3 color)
{
    return acesFilmic(color);
}
