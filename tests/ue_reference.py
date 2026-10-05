"""Independent NumPy UE algorithm reference (FP32 textures, float64 algebra).

Builds Gaussian weights independently of the runtime bilinear tap builder.
Does not import or execute the port's shaders. This is not an Unreal capture.
"""
import math
import numpy as np


def detect_sampler_bits(device):
    """Measure a ramp independently; never fit sampling precision to LE errors."""
    from pathlib import Path
    import slangpy as spy
    source = device.create_texture(width=2, height=1, format=spy.Format.r32_float,
        usage=spy.TextureUsage.shader_resource, data=np.array([[0, 1]], np.float32))
    out = device.create_texture(width=1021, height=1, format=spy.Format.r32_float,
        usage=spy.TextureUsage.shader_resource | spy.TextureUsage.unordered_access)
    sampler = device.create_sampler(min_filter=spy.TextureFilteringMode.linear, mag_filter=spy.TextureFilteringMode.linear,
        address_u=spy.TextureAddressingMode.clamp_to_edge, address_v=spy.TextureAddressingMode.clamp_to_edge)
    session = device.create_slang_session()
    kernel = device.create_compute_kernel(session.load_program(str(Path(__file__).with_name('fixtures') / 'ue_sampler_probe.slang'), ['sample_probe']))
    kernel.dispatch(thread_count=[1021, 1, 1], vars=dict(inputTexture=source, outputTexture=out, linearSampler=sampler))
    actual = out.to_numpy()[0]
    t = (np.arange(1021, dtype=np.float32) + np.float32(.37)) / np.float32(1021)
    if np.max(abs(actual - t)) < 2e-6:
        return None
    for bits in range(4, 17):
        if np.max(abs(actual - np.round(t * 2 ** bits) / 2 ** bits)) < 2e-6:
            return bits
    raise RuntimeError('Sampler ramp does not match an independently measured interpolation model')


def sample(image, u, v, mirror=False, fraction_bits=None):
    h, w = image.shape[:2]
    image = image[..., None] if image.ndim == 2 else image
    # Shader coordinates are FP32. At a hardware interpolation rounding tie,
    # float64 coordinates select a different tap fraction even for exact UVs.
    x = np.asarray(u, np.float32) * np.float32(w) - np.float32(.5)
    y = np.asarray(v, np.float32) * np.float32(h) - np.float32(.5)
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    fx, fy = (x - x0)[..., None], (y - y0)[..., None]
    if fraction_bits is not None:
        steps = 2 ** fraction_bits
        fx, fy = np.round(fx * steps) / steps, np.round(fy * steps) / steps

    def address(i, n):
        if not mirror:
            return np.clip(i, 0, n - 1)
        j = i % (2 * n)
        return np.minimum(j, 2 * n - 1 - j)

    a = image[address(y0, h), address(x0, w)]
    b = image[address(y0, h), address(x0 + 1, w)]
    c = image[address(y0 + 1, h), address(x0, w)]
    d = image[address(y0 + 1, h), address(x0 + 1, w)]
    value = (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy
    return value[..., 0] if value.shape[-1] == 1 else value


def coordinates(w, h):
    y, x = np.mgrid[:h, :w]
    return (x.astype(np.float32) + np.float32(.5)) / np.float32(w), (y.astype(np.float32) + np.float32(.5)) / np.float32(h)


def downsample(image, high=True, fraction_bits=None):
    h, w = image.shape[:2]
    u, v = coordinates((w + 1) // 2, (h + 1) // 2)
    if not high:
        return sample(image, u, v, fraction_bits=fraction_bits).astype(np.float32)
    return (sum(sample(image, u + x / w, v + y / h, fraction_bits=fraction_bits)
                for x, y in [(-1, -1), (1, -1), (-1, 1), (1, 1)]) * .25).astype(np.float32)


def eye_luminance(rgb, p):
    return np.maximum(np.asarray(rgb, np.float64) @ np.array(p.luminance_weights), 2 ** p.histogram_min)


def film_neutral(lum, p):
    toe_scale = 1 + p.film_black_clip - p.film_toe
    shoulder_scale = 1 + p.film_white_clip - p.film_shoulder
    if p.film_toe > .8:
        toe_match = (1 - p.film_toe - .18) / p.film_slope + math.log10(.18)
    else:
        bt = (.18 + p.film_black_clip) / toe_scale - 1
        toe_match = math.log10(.18) - .5 * math.log((1 + bt) / (1 - bt)) * toe_scale / p.film_slope
    straight_match = (1 - p.film_toe) / p.film_slope - toe_match
    shoulder_match = p.film_shoulder / p.film_slope - straight_match
    with np.errstate(divide='ignore', over='ignore'):
        log_lum = np.log10(lum)
        linear = p.film_slope * (log_lum + straight_match)
        low = -p.film_black_clip + 2 * toe_scale / (1 + np.exp(-2 * p.film_slope / toe_scale * (log_lum - toe_match)))
        high = 1 + p.film_white_clip - 2 * shoulder_scale / (1 + np.exp(2 * p.film_slope / shoulder_scale * (log_lum - shoulder_match)))
    a = np.where(log_lum < toe_match, low, linear)
    b = np.where(log_lum > shoulder_match, high, linear)
    t = np.clip((log_lum - toe_match) / (shoulder_match - toe_match), 0, 1)
    if shoulder_match < toe_match:
        t = 1 - t
    t = t * t * (3 - 2 * t)
    return np.maximum(a * (1 - t) + b * t, 0)


def inverse_fusion(lum, result):
    y = np.clip(np.minimum(result, 1) ** 2, 0, 1)
    with np.errstate(divide='ignore'):
        toe = .374816 * (0.9 / np.minimum(y, .8) - 1) ** (-.588729)
    shoulder = .227986 * (1.56 / (1.04 - y) - 1) ** 1.02046
    blend = np.clip((y - .35) / .1, 0, 1)
    blend = blend ** 2 * (3 - 2 * blend)
    return np.maximum(toe * (1 - blend) + shoulder * blend, 0) / lum


def fusion(rgb, p, ev=0, highlight=.8, shadow=.8, levels=16, fraction_bits=None):
    lum = eye_luminance(rgb / p.pre_exposure * 2 ** ev, p)
    exposures = np.sqrt(film_neutral(lum[..., None] * [1, 2 ** (-6 * (1 - highlight)), 2 ** (6 * (1 - shadow))], p))
    weights = np.exp2(-(exposures - p.target_luminance) ** 2 / .08)
    weights /= weights.sum(axis=-1, keepdims=True)
    e, w = [exposures.astype(np.float32)], [weights.astype(np.float32)]
    for _ in range(1, min(levels, min(lum.shape).bit_length())):
        e.append(downsample(e[-1], fraction_bits=fraction_bits))
        w.append(downsample(w[-1], fraction_bits=fraction_bits))
    result = None
    for i in range(len(e) - 1, -1, -1):
        h, width = e[i].shape[:2]
        u, v = coordinates(width, h)
        detail = e[i].astype(np.float64)
        previous = 0
        if result is not None:
            detail -= sample(e[i + 1], u, v, fraction_bits=fraction_bits)
            previous = sample(result, u, v, fraction_bits=fraction_bits)
        weights = w[i].astype(np.float64)
        weights /= weights.sum(axis=-1, keepdims=True)
        result = (previous + (weights * detail).sum(axis=-1)).astype(np.float32)
    return dict(exposures=e, weights=w, fused=result, exposure=inverse_fusion(lum, result))


def grid_reference(rgb, p):
    h, w = rgb.shape[:2]
    result = np.zeros((32, (h + 63) // 64, (w + 63) // 64, 2), np.float32)
    # GPU performs FP32 histogram mapping before fixed-point quantization.
    lum = np.maximum(np.sum(rgb.astype(np.float32) * np.array(p.luminance_weights, np.float32), axis=-1),
                     np.float32(2 ** p.histogram_min))
    position = ((np.log2(lum) - np.float32(p.histogram_min)) /
                np.float32(p.histogram_max - p.histogram_min)).astype(np.float32)
    for gy in range(result.shape[1]):
        for gx in range(result.shape[2]):
            rows, cols = np.mgrid[gy * 64:min((gy + 1) * 64, h - h % 2),
                                  gx * 64:min((gx + 1) * 64, w - w % 2)]
            pos = position[rows, cols]
            bucket = np.clip(pos, 0, 1) * np.float32(31)
            lo = bucket.astype(int)
            fraction = bucket - lo.astype(np.float32)
            histogram = np.zeros((32, 8, 8), np.uint32)
            for b, weight in [(lo, 1 - fraction), (np.minimum(lo + 1, 31), fraction)]:
                packed = (((weight * 512).astype(np.uint32) & 65535) << 16) | (((pos * weight * 512).astype(np.uint32)) & 65535)
                np.add.at(histogram, (b.ravel(), ((cols // 2) % 8).ravel(), ((rows // 2) % 8).ravel()), packed.ravel())
            sum_weight = np.zeros(32, np.float32)
            sum_lum = np.zeros(32, np.float32)
            for y in range(8):
                for x in range(8):
                    value = histogram[:, x, y]
                    weight = (value >> 16).astype(np.float32) / 512
                    moment = (value & 65535).astype(np.float32) / 512
                    sum_weight += weight
                    sum_lum += moment * np.float32(p.histogram_max - p.histogram_min) + weight * np.float32(p.histogram_min)
            result[:, gy, gx, 0] = sum_lum
            result[:, gy, gx, 1] = sum_weight
    return result


def discrete_blur(image, percent, fraction_bits=None):
    h, w = image.shape
    radius = np.clip(w * percent * .005, 1e-5, 31)
    ir = max(1, math.ceil(radius))
    offsets = np.arange(-ir, ir + 1)
    weights = np.exp(-16.7 * (offsets / radius) ** 2)
    weights /= weights.sum()
    # UE evaluates paired bilinear taps even when fast blur's base coordinates
    # fall between texel centers. Preserve that sampling rather than assuming
    # equivalence to a discrete convolution at arbitrary fractional positions.
    pairs = []
    for i in range(0, len(weights), 2):
        a, b = weights[i], weights[i + 1] if i + 1 < len(weights) else 0
        total = a + b
        pairs.append((np.float32(offsets[i] + (b / total if total else 0)), np.float32(total)))
    u, v = coordinates((w + 1) // 2 if w * percent * .005 >= 7 else w, h)
    horizontal = sum(sample(image, u + i / w, v, mirror=True, fraction_bits=fraction_bits) * weight for i, weight in pairs).astype(np.float32)
    u, v = coordinates(w, h)
    return sum(sample(horizontal, u, v + i / h, mirror=True, fraction_bits=fraction_bits) * weight for i, weight in pairs).astype(np.float32)


def slice_grid(grid, u, v, z, fraction_bits=None):
    depth = grid.shape[0]
    q = np.clip(np.asarray(z, np.float32) * np.float32(depth) - np.float32(.5), 0, depth - 1)
    lo, hi = np.floor(q).astype(int), np.minimum(np.floor(q).astype(int) + 1, depth - 1)
    planes = np.stack([sample(plane, u, v, fraction_bits=fraction_bits) for plane in grid], axis=0)
    y, x = np.indices(u.shape)
    t = (q - lo)[..., None]
    if fraction_bits is not None:
        t = np.round(t * 2 ** fraction_bits) / 2 ** fraction_bits
    return planes[lo, y, x] * (1 - t) + planes[hi, y, x] * t


def bilateral(rgb, p, ev=0, highlight=.8, shadow=.8, fraction_bits=None):
    chain = [rgb.astype(np.float32)]
    if p.profile == 'desktop':
        for i in range(5):
            chain.append(downsample(chain[-1], high=i > 0, fraction_bits=fraction_bits))
    grid_source = chain[1] if p.profile == 'desktop' else chain[0]
    grid = grid_reference(grid_source / p.pre_exposure, p)
    log_texture = np.log2(eye_luminance(chain[-1] / p.pre_exposure, p)).astype(np.float32)
    blur = discrete_blur(log_texture, p.blur_percent, fraction_bits=fraction_bits) if p.blurred_blend > 0 else np.zeros_like(log_texture)
    log_lum = np.log2(eye_luminance(rgb / p.pre_exposure, p))
    h, w = log_lum.shape
    u, v = coordinates(w, h)
    uv_scale = (grid_source.shape[1] / (64 * grid.shape[2]), grid_source.shape[0] / (64 * grid.shape[1]))
    position = (log_lum - p.histogram_min) / (p.histogram_max - p.histogram_min)
    sampled = slice_grid(grid, u * uv_scale[0], v * uv_scale[1], (position * 31 + .5) / 32, fraction_bits=fraction_bits)
    blurred = sample(blur, u, v, fraction_bits=fraction_bits)
    average = np.divide(sampled[..., 0], sampled[..., 1], out=np.array(blurred, copy=True), where=sampled[..., 1] >= .001)
    base = average * (1 - p.blurred_blend) + blurred * p.blurred_blend + ev
    middle = np.log2(.18 * p.grey_multiplier) + p.middle_grey_bias
    log_lum += ev
    centered = base - middle
    positive = centered > 0
    threshold = np.where(positive, p.highlight_threshold, p.shadow_threshold)
    strength = np.where(positive, p.highlight_threshold_strength, p.shadow_threshold_strength)
    m = np.where(positive, np.maximum(centered - threshold, 0), np.minimum(centered + threshold, 0))
    t = np.clip((np.abs(centered) - threshold) * (1 - strength), 0, 1)
    t = t * t * (3 - 2 * t)
    offset = (centered - m) * (1 - t)
    contrast = np.where(positive, highlight, shadow)
    exposure = np.exp2(middle + offset + (centered - offset) * contrast + (log_lum - base) * p.detail_strength - log_lum)
    return dict(chain=chain, grid=grid, log=log_texture, blur=blur, base=base, exposure=exposure)
